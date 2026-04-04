import os
import requests
import json
import hashlib
import uvicorn
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.generativeai as genai

app = FastAPI()

# --- CONFIGURACION — nombres alineados al .env ---
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY")
SHOPIFY_TOKEN      = os.getenv("SHOPIFY_ACCESS_TOKEN")
SHOP_NAME          = os.getenv("SHOPIFY_SHOP_NAME")
API_VER            = os.getenv("SHOPIFY_API_VERSION", "2024-10")
BASE_URL           = f"https://{SHOP_NAME}.myshopify.com/admin/api/{API_VER}"

MAILCHIMP_API_KEY  = os.getenv("MAILCHIMP_API_KEY")
MAILCHIMP_DC       = os.getenv("MAILCHIMP_DC", "us7")           # <- igual que .env
MAILCHIMP_LIST_ID  = os.getenv("MAILCHIMP_AUDIENCE_ID")         # <- igual que .env
MAILCHIMP_BASE_URL = f"https://{MAILCHIMP_DC}.api.mailchimp.com/3.0"

genai.configure(api_key=GEMINI_API_KEY)

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MODELOS ---
class EmailSubscription(BaseModel):
    email: str
    skin_type: str
    skin_tag: str
    products: list


# --- MAILCHIMP ---
def subscribe_to_mailchimp(email: str, skin_type: str, skin_tag: str, products: list):
    headers = {
        "Authorization": f"Bearer {MAILCHIMP_API_KEY}",
        "Content-Type": "application/json"
    }

    email_hash    = hashlib.md5(email.lower().encode()).hexdigest()
    product_names = " | ".join([p.get("title", "") for p in products[:3]])
    member_url    = f"{MAILCHIMP_BASE_URL}/lists/{MAILCHIMP_LIST_ID}/members/{email_hash}"

    check = requests.get(member_url, headers=headers)

    if check.status_code == 200:
        # Contacto existente: actualizar sin disparar bienvenida
        current_status = check.json().get("status", "subscribed")
        requests.patch(member_url, headers=headers, json={
            "status": current_status,
            "merge_fields": {
                "SKIN_TYPE": skin_type,
                "PRODUCTS":  product_names,
            }
        })
        requests.post(f"{member_url}/tags", headers=headers, json={
            "tags": [{"name": f"piel-{skin_tag}", "status": "active"}]
        })
        print(f"Mailchimp: contacto existente actualizado ({email})")
        return {"status": "updated", "message": "Contacto existente actualizado"}

    else:
        # Nuevo contacto: disparar bienvenida
        res = requests.post(
            f"{MAILCHIMP_BASE_URL}/lists/{MAILCHIMP_LIST_ID}/members",
            headers=headers,
            json={
                "email_address": email,
                "status": "subscribed",
                "merge_fields": {
                    "SKIN_TYPE": skin_type,
                    "PRODUCTS":  product_names,
                },
                "tags": [f"piel-{skin_tag}", "analizador-ia"]
            }
        )
        if res.status_code in [200, 204]:
            print(f"Mailchimp: nuevo contacto suscrito ({email})")
            return {"status": "subscribed", "message": "Nuevo contacto agregado"}
        else:
            print(f"Mailchimp error: {res.text}")
            return {"status": "error", "message": res.text}


# --- SHOPIFY ---
def get_shopify_recommendations(skin_tag):
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json"
    }

    search_tag = skin_tag.lower().strip()
    print(f"Buscando productos con tag: '{search_tag}'")

    try:
        response = requests.get(
            f"{BASE_URL}/products.json?tag={search_tag}&limit=50",
            headers=headers,
            timeout=10
        )
        if response.status_code != 200:
            print(f"Error Shopify: {response.status_code}")
            return []

        valid = []
        for p in response.json().get('products', []):
            variants = p.get('variants', [])
            if not variants:
                continue
            v = variants[0]
            if v.get('inventory_quantity', 0) <= 0:
                continue

            image_url = None
            if p.get('image'):
                image_url = p['image']['src']
            elif p.get('images'):
                image_url = p['images'][0]['src']

            valid.append({
                "title":      p['title'],
                "variant_id": str(v['id']),
                "price":      v['price'],
                "image":      image_url,
                "handle":     p['handle'],
                "stock":      v.get('inventory_quantity', 0)
            })

        print(f"Productos validos: {len(valid)}")
        return valid

    except Exception as e:
        print(f"Error Shopify: {e}")
        return []


# --- RUTA: ANALISIS ---
@app.post("/analyze")
async def analyze_skin(file: UploadFile = File(...)):
    try:
        image_bytes = await file.read()

        available_models = [
            m.name for m in genai.list_models()
            if 'generateContent' in m.supported_generation_methods
        ]
        target_model = (
            'models/gemini-1.5-flash'
            if 'models/gemini-1.5-flash' in available_models
            else available_models[0]
        )

        model  = genai.GenerativeModel(target_model)
        prompt = """
        Eres una experta en skincare coreano de Moonbow, una tienda especializada en belleza coreana en Chile.

        Tu rol es analizar la piel de una persona a partir de una imagen facial y entregar un diagnóstico claro, confiable y fácil de entender.

        IMPORTANTE SOBRE LA IMAGEN:
        - Primero debes verificar si la imagen contiene un rostro humano real.
        - Si NO es un rostro humano claro (por ejemplo: objeto, dibujo, múltiples rostros, baja calidad o rostro no visible), responde con:
        {
        "error": "no_face_detected"
        }
        - No intentes analizar imágenes que no sean rostros humanos.

        TONO Y ESTILO (MUY IMPORTANTE):
        - Usa un lenguaje cercano, claro y amigable
        - Mantén un tono experto pero no médico
        - Evita términos técnicos complejos
        - Habla como una asesora de belleza, no como un doctor
        - Sé breve, directo y útil

        OBJETIVO:
        Entregar un diagnóstico que ayude a la persona a entender su piel y qué necesita mejorar.

        FORMATO DE RESPUESTA:
        Debes responder SOLO en JSON válido.
        NO incluyas texto fuera del JSON.
        NO incluyas explicaciones adicionales.

        Estructura obligatoria:

        {
        "tipo_piel": "Piel Grasa | Piel Seca | Piel Mixta | Piel Sensible",
        "tipo_piel_tag": "grasa | seca | mixta | sensible",
        "analisis": "Explicación breve (2-3 líneas) clara y entendible sobre el estado de la piel",
        "puntos_clave": [
            "3 a 5 observaciones simples y útiles (ej: Brillo en zona T, Poros visibles, etc)"
        ],
        "hidratacion": "baja | media | optima",
        "elasticidad": "numero entre 50 y 100",
        "sensibilidad": "alta | media | baja",
        "edad_piel": numero o null
        }

        REGLAS IMPORTANTES:
        - El análisis debe ser fácil de entender para cualquier persona
        - No inventes enfermedades ni condiciones médicas
        - No menciones marcas ni productos
        - No recomiendes productos directamente
        - Sé consistente con los valores entregados
        - Si hay dudas en la imagen, elige la opción más conservadora
        - Mantén coherencia entre tipo de piel y puntos_clave

        EJEMPLO DE TONO:

        "Piel mixta con brillo en la zona T y mejillas más equilibradas. Se observa hidratación media, pero con tendencia a poros visibles en la zona central del rostro."

        """

        response = model.generate_content(
            [
                prompt,
                {"mime_type": "image/jpeg", "data": image_bytes}
            ],
            generation_config={
                "temperature": 0.2,  # 🔥 clave → menos creatividad = más consistente
                "top_p": 0.8,
                "top_k": 40,
                "max_output_tokens": 500
            }
        )

        if not response or not response.text:
            raise Exception("Gemini no respondio.")

        res_text = response.text.strip()
        if "```json" in res_text:
            res_text = res_text.split("```json")[1].split("```")[0].strip()
        elif "```" in res_text:
            res_text = res_text.split("```")[1].split("```")[0].strip()

        analysis_data = json.loads(res_text)
        print(f"Tipo: {analysis_data.get('tipo_piel')} | H:{analysis_data.get('hidratacion')} E:{analysis_data.get('elasticidad')} S:{analysis_data.get('sensibilidad')} Edad:{analysis_data.get('edad_piel')}")

        recommendations = get_shopify_recommendations(analysis_data.get('tipo_piel_tag', ''))

        return {
            "result":   json.dumps(analysis_data),
            "products": recommendations
        }

    except Exception as e:
        print(f"Error critico: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# --- RUTA: SUSCRIPCION MAILCHIMP ---
@app.post("/subscribe")
async def subscribe(data: EmailSubscription):
    try:
        result = subscribe_to_mailchimp(
            email=data.email,
            skin_type=data.skin_type,
            skin_tag=data.skin_tag,
            products=data.products
        )
        return result
    except Exception as e:
        print(f"Error suscripcion: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# --- INICIO para Cloud Run ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)