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

# --- 1. CONFIGURACIÓN DE APIS ---

# Google Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("❌ ERROR: GEMINI_API_KEY no encontrada en .env")
genai.configure(api_key=GEMINI_API_KEY)

# Shopify
SHOPIFY_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN")
SHOP_NAME = os.getenv("SHOPIFY_SHOP_NAME")
API_VER = os.getenv("SHOPIFY_API_VERSION", "2024-10")
BASE_URL = f"https://{SHOP_NAME}.myshopify.com/admin/api/{API_VER}"

# Mailchimp
MAILCHIMP_API_KEY = os.getenv("MAILCHIMP_API_KEY")
MAILCHIMP_REGION = os.getenv("MAILCHIMP_REGION") # Ejemplo: us21
MAILCHIMP_LIST_ID = os.getenv("MAILCHIMP_LIST_ID")

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
    """
    - Si el contacto YA existe: actualiza sus datos sin disparar bienvenida
    - Si es NUEVO: lo agrega y dispara el flujo de bienvenida de Mailchimp
    """
    headers = {
        "Authorization": f"Bearer {MAILCHIMP_API_KEY}",
        "Content-Type": "application/json"
    }

    email_hash = hashlib.md5(email.lower().encode()).hexdigest()
    product_names = " | ".join([p.get("title", "") for p in products[:3]])

    check_url = f"{MAILCHIMP_BASE_URL}/lists/{MAILCHIMP_AUDIENCE_ID}/members/{email_hash}"
    check_response = requests.get(check_url, headers=headers)

    if check_response.status_code == 200:
        # Contacto existente — solo actualizamos, NO disparamos bienvenida
        existing = check_response.json()
        current_status = existing.get("status", "subscribed")

        update_data = {
            "status": current_status,
            "merge_fields": {
                "SKIN_TYPE": skin_type,
                "PRODUCTS": product_names,
            }
        }
        requests.patch(check_url, headers=headers, json=update_data)

        # Agregar tag de tipo de piel
        tags_url = f"{check_url}/tags"
        requests.post(tags_url, headers=headers, json={
            "tags": [{"name": f"piel-{skin_tag}", "status": "active"}]
        })

        print(f"✅ Mailchimp: contacto existente actualizado ({email})")
        return {"status": "updated", "message": "Contacto existente actualizado"}

    else:
        # Nuevo contacto — se dispara bienvenida automáticamente
        subscribe_data = {
            "email_address": email,
            "status": "subscribed",
            "merge_fields": {
                "SKIN_TYPE": skin_type,
                "PRODUCTS": product_names,
            },
            "tags": [f"piel-{skin_tag}", "analizador-ia"]
        }

        post_url = f"{MAILCHIMP_BASE_URL}/lists/{MAILCHIMP_AUDIENCE_ID}/members"
        post_response = requests.post(post_url, headers=headers, json=subscribe_data)

        if post_response.status_code in [200, 204]:
            print(f"✅ Mailchimp: nuevo contacto suscrito ({email})")
            return {"status": "subscribed", "message": "Nuevo contacto agregado"}
        else:
            print(f"❌ Mailchimp error: {post_response.text}")
            return {"status": "error", "message": post_response.text}


# --- SHOPIFY ---
def get_shopify_recommendations(skin_tag):
    headers = {
        "X-Shopify-Access-Token": ACCESS_TOKEN,
        "Content-Type": "application/json"
    }

    search_tag = skin_tag.lower().strip()
    print(f"🔍 Buscando productos con tag: '{search_tag}'")
    endpoint = f"{BASE_URL}/products.json?tag={search_tag}&limit=50"

    try:
        response = requests.get(endpoint, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"❌ Error Shopify: {response.status_code}")
            return []

        products = response.json().get('products', [])
        valid = []

        for p in products:
            variants = p.get('variants', [])
            if not variants:
                continue
            first_variant = variants[0]
            if first_variant.get('inventory_quantity', 0) <= 0:
                continue

            image_url = None
            if p.get('image'):
                image_url = p['image']['src']
            elif p.get('images'):
                image_url = p['images'][0]['src']

            valid.append({
                "title": p['title'],
                "variant_id": str(first_variant['id']),
                "price": first_variant['price'],
                "image": image_url,
                "handle": p['handle'],
                "stock": first_variant.get('inventory_quantity', 0)
            })
            print(f"  ✅ {p['title']} | variant_id: {first_variant['id']}")

        return valid

    except Exception as e:
        print(f"❌ Error Shopify: {e}")
        return []


# --- RUTA: ANÁLISIS ---
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

        model = genai.GenerativeModel(target_model)

        # Prompt actualizado: ahora pide hidratación, elasticidad y sensibilidad reales
        prompt = """
        Eres un experto en dermatología y K-Beauty de Moonbow.cl.
        Analiza la imagen del rostro y devuelve UNICAMENTE un JSON, sin texto adicional ni backticks.

        Reglas estrictas:
        - tipo_piel_tag: exactamente uno de [grasa, seca, mixta, sensible]
        - hidratacion: exactamente uno de [Baja, Media, Óptima]
        - elasticidad: número entero entre 50 y 99
        - sensibilidad: exactamente uno de [Baja, Media, Alta]
        - edad_piel: número entero, edad estimada de la piel según textura, poros y luminosidad

        Formato:
        {
          "tipo_piel": "Piel Grasa",
          "tipo_piel_tag": "grasa",
          "analisis": "Explicación técnica de 2-3 oraciones basada en lo que ves en la imagen.",
          "puntos_clave": ["punto 1", "punto 2", "punto 3"],
          "rutina_sugerida": "Pasos recomendados",
          "hidratacion": "Óptima",
          "elasticidad": "85",
          "sensibilidad": "Baja"
        }
        """

        response = model.generate_content([
            prompt,
            {"mime_type": "image/jpeg", "data": image_bytes}
        ])

        if not response or not response.text:
            raise Exception("Gemini no respondió.")

        res_text = response.text.strip()
        if "```json" in res_text:
            res_text = res_text.split("```json")[1].split("```")[0].strip()
        elif "```" in res_text:
            res_text = res_text.split("```")[1].split("```")[0].strip()

        analysis_data = json.loads(res_text)
        print(f"🧴 {analysis_data.get('tipo_piel')} | H:{analysis_data.get('hidratacion')} E:{analysis_data.get('elasticidad')} S:{analysis_data.get('sensibilidad')}")

        recommendations = get_shopify_recommendations(analysis_data.get('tipo_piel_tag', ''))

        return {
            "result": json.dumps(analysis_data),
            "products": recommendations
        }

    except Exception as e:
        print(f"❌ Error crítico: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# --- RUTA: SUSCRIPCIÓN MAILCHIMP ---
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
        print(f"❌ Error suscripción: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)