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
        Eres un experto en dermatologia y K-Beauty de Moonbow.cl.
        Analiza la imagen del rostro y devuelve UNICAMENTE un JSON, sin texto adicional ni backticks.

        Reglas estrictas:
        - tipo_piel_tag: exactamente uno de [grasa, seca, mixta, sensible]
        - hidratacion: exactamente uno de [Baja, Media, Optima]
        - elasticidad: numero entero entre 50 y 99
        - sensibilidad: exactamente uno de [Baja, Media, Alta]
        - edad_piel: numero entero, edad estimada de la piel segun textura, poros y luminosidad

        Formato:
        {
          "tipo_piel": "Piel Grasa",
          "tipo_piel_tag": "grasa",
          "analisis": "Explicacion tecnica de 2-3 oraciones basada en lo que ves en la imagen.",
          "puntos_clave": ["punto 1", "punto 2", "punto 3"],
          "rutina_sugerida": "Pasos recomendados",
          "hidratacion": "Optima",
          "elasticidad": "85",
          "sensibilidad": "Baja",
          "edad_piel": "28"
        }
        """

        response = model.generate_content([
            prompt,
            {"mime_type": "image/jpeg", "data": image_bytes}
        ])

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