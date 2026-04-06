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
    allow_origins=[
        "http://localhost:5173",
        "https://moonbow-skin-ai.vercel.app",
        "https://moonbow.cl",
        "https://www.moonbow.cl"
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
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

# --- COLECCIONES SHOPIFY ---
COLLECTIONS = {
    "oil-cleanser": ["limpiadores-oleosos-desmaquillantes"],
    "foam-cleanser": ["limpiador-en-espuma"],
    "toner": ["tonicos"],
    "serum": ["serum"],
    "eye-cream": ["contorno-de-ojos"],
    "moisturizer": ["cremas-y-lociones"],
    "sunscreen": ["protector-solar"]
}

# FUNCION PARA EXTRAER EL JSON DE LA RESPUESTA DE GEMINI
import re

def extract_json(text):
    try:
        # intenta parse directo
        return json.loads(text)
    except:
        pass

    try:
        # intenta extraer bloque JSON
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except:
        pass

    print("⚠️ No se pudo parsear JSON")
    return {}

# FUNCION PARA EXTRAER LAS NECESIDADES DE LA PIEL
def extract_skin_needs(analysis):
    needs = []

    hidratacion = analysis.get("hidratacion", "").lower()
    if hidratacion == "baja":
        needs.append("hidratacion")
    elif hidratacion == "media":
        needs.append("hidratacion")  # igual incluir, es un need relevante

    sensibilidad = analysis.get("sensibilidad", "").lower()
    if sensibilidad == "alta":
        needs.append("calmante")
        needs.append("sensible")

    tipo_piel = analysis.get("tipo_piel_tag", "").lower()
    if tipo_piel in ["grasa", "mixta"]:
        needs.append("poros")
        needs.append("sebo")
    if tipo_piel == "seca":
        needs.append("hidratacion")
        needs.append("nutricion")

    edad_piel = int(analysis.get("edad_piel", 30))
    if edad_piel >= 30:
        needs.append("anti-edad")
        needs.append("firmeza")

    rutina = analysis.get("rutina_sugerida", "").lower()
    puntos = " ".join(analysis.get("puntos_clave", [])).lower() + " " + rutina

    if "poro" in puntos:
        needs.append("poros")
    if "arruga" in puntos or "linea" in puntos or "firmeza" in puntos:
        needs.append("anti-edad")
        needs.append("firmeza")
    if "mancha" in puntos or "uniform" in puntos:
        needs.append("manchas")
        needs.append("iluminador")
    if "acne" in puntos or "acné" in puntos or "grano" in puntos:
        needs.append("acne")
    if "brillo" in puntos or "grasa" in puntos or "sebo" in puntos:
        needs.append("sebo")
        needs.append("poros")
    if "hidrat" in puntos or "seca" in puntos or "tension" in puntos:
        needs.append("hidratacion")
    if "rojez" in puntos or "irritad" in puntos or "calm" in puntos:
        needs.append("calmante")

    return list(set(needs))

# --- FUNCION PARA OBTENER LOS PRODUCTOS DE LAS COLECCIONES SHOPIFY ---
def get_products_by_collection(handle):
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json"
    }

    try:
        collection_id = None
        collection_type = None

        # 1. Buscar en custom_collections (manuales)
        res = requests.get(
            f"{BASE_URL}/custom_collections.json?handle={handle}",
            headers=headers,
            timeout=10
        )
        if res.status_code == 200:
            custom = res.json().get("custom_collections", [])
            if custom:
                collection_id = custom[0]["id"]
                collection_type = "custom"

        # 2. Si no se encontró, buscar en smart_collections (automáticas)
        if not collection_id:
            res = requests.get(
                f"{BASE_URL}/smart_collections.json?handle={handle}",
                headers=headers,
                timeout=10
            )
            if res.status_code == 200:
                smart = res.json().get("smart_collections", [])
                if smart:
                    collection_id = smart[0]["id"]
                    collection_type = "smart"

        if not collection_id:
            print(f"  ❌ Colección '{handle}' NO encontrada (ni custom ni smart). HTTP status custom={res.status_code}")
            return []

        print(f"  ✅ Colección '{handle}' [{collection_type}] id={collection_id}")

        # 3. Obtener productos de la colección
        res = requests.get(
            f"{BASE_URL}/products.json?collection_id={collection_id}&limit=50",
            headers=headers,
            timeout=10
        )
        products = res.json().get("products", [])
        print(f"     → {len(products)} productos encontrados")

        return products

    except Exception as e:
        print(f"  ❌ Error colección '{handle}': {e}")
        return []
# --- SHOPIFY ---

# Orden canónico de la rutina (determina el orden de presentación al usuario)
ROUTINE_ORDER = [
    "oil-cleanser",
    "foam-cleanser",
    "toner",
    "serum",
    "eye-cream",
    "moisturizer",
    "sunscreen",
]

# Tags de tipo de piel compatibles por tipo principal (fallback)
SKIN_TYPE_COMPATIBILITY = {
    "grasa":    ["grasa", "mixta", "normal"],
    "mixta":    ["mixta", "grasa", "normal"],
    "seca":     ["seca", "normal", "sensible"],
    "sensible": ["sensible", "seca", "normal"],
    "normal":   ["normal", "mixta", "seca", "grasa"],
}

def score_product(p, tipo_piel, needs, category):
    """
    Devuelve un score numérico para un producto dado el tipo de piel y las necesidades.
    Mayor score = mejor recomendación.
    """
    tags = [t.lower().strip() for t in p.get("tags", "").split(",")]
    score = 0

    # 1. Coincidencia de tipo de piel (ponderación máxima)
    compatible = SKIN_TYPE_COMPATIBILITY.get(tipo_piel, [tipo_piel])
    if tipo_piel and tipo_piel in tags:
        score += 20              # match exacto
    elif any(t in tags for t in compatible):
        score += 10              # match compatible
    elif "todo-tipo" in tags or "all-skin" in tags or "all skin" in tags:
        score += 8               # apto para todo tipo
    # Si no hay ningún match de tipo de piel, igual sigue (no se descarta)

    # 2. Necesidades de la piel
    for need in needs:
        if need in tags:
            score += 5

    # 3. Best seller / destacado
    if "best-seller" in tags or "bestseller" in tags:
        score += 8
    if "destacado" in tags or "featured" in tags:
        score += 4

    # 4. Stock suficiente (favorece productos con más stock)
    variants = p.get("variants", [])
    if variants:
        v = variants[0]
        qty = v.get("inventory_quantity", 0)
        if qty > 20:
            score += 3
        elif qty > 5:
            score += 1

    # 5. Tiene imagen (mejor UX)
    if p.get("image") or p.get("images"):
        score += 2

    return score


def build_product_entry(p, category):
    """Construye el dict de producto para la respuesta."""
    variants = p.get("variants", [])
    if not variants:
        return None
    v = variants[0]
    if v.get("inventory_quantity", 0) <= 0:
        return None

    image_url = None
    if p.get("image"):
        image_url = p["image"]["src"]
    elif p.get("images"):
        image_url = p["images"][0]["src"]

    return {
        "title":      p["title"],
        "variant_id": str(v["id"]),
        "price":      v["price"],
        "image":      image_url,
        "handle":     p["handle"],
        "category":   category,
    }


def get_shopify_recommendations(analysis):
    tipo_piel = analysis.get("tipo_piel_tag", "").lower().strip()
    needs     = extract_skin_needs(analysis)

    print(f"Tipo piel: {tipo_piel}")
    print(f"Needs detectados: {needs}")

    # Decide si incluir oil cleanser (doble limpieza)
    include_oil = tipo_piel in ["grasa", "mixta"] or any(
        n in ["poros", "sebo", "acne"] for n in needs
    )

    final_products = []

    for category in ROUTINE_ORDER:

        if category == "oil-cleanser" and not include_oil:
            continue

        handles = COLLECTIONS.get(category, [])
        if not handles:
            continue

        # Recolectar todos los productos de la categoría
        all_products = []
        for handle in handles:
            all_products.extend(get_products_by_collection(handle))

        if not all_products:
            handles_str = ", ".join(handles)
            print(f"⚠️  Sin productos en categoría: {category} (handles buscados: [{handles_str}])")
            continue

        # Eliminar duplicados por id
        seen_ids = set()
        unique_products = []
        for p in all_products:
            pid = p.get("id")
            if pid not in seen_ids:
                seen_ids.add(pid)
                unique_products.append(p)

        # Filtrar solo los que tienen stock o no tienen tracking de inventario
        def is_available(p):
            variants = p.get("variants", [])
            if not variants:
                return False
            v = variants[0]
            # Si no trackea inventario (inventory_management=null), se asume disponible
            if v.get("inventory_management") is None or v.get("inventory_management") == "":
                return True
            # Si trackea, verificar quantity > 0 o política "continue" (vender sin stock)
            if v.get("inventory_policy") == "continue":
                return True
            return v.get("inventory_quantity", 0) > 0

        with_stock = [p for p in unique_products if is_available(p)]

        if not with_stock:
            # Log detallado para diagnosticar
            sample = unique_products[:2]
            for sp in sample:
                v = sp.get("variants", [{}])[0]
                print(f"  ⚠️  Stock 0: '{sp['title'][:40]}' "
                      f"inv_mgmt={v.get('inventory_management')} "
                      f"qty={v.get('inventory_quantity')} "
                      f"policy={v.get('inventory_policy')}")
            print(f"⚠️  Sin stock en categoría: {category} ({len(unique_products)} prods sin stock)")
            continue

        # Puntuar todos los productos con stock
        scored = []
        for p in with_stock:
            s = score_product(p, tipo_piel, needs, category)
            entry = build_product_entry(p, category)
            if entry:
                entry["_score"] = s
                scored.append(entry)

        if not scored:
            continue

        # Ordenar por score descendente
        scored.sort(key=lambda x: x["_score"], reverse=True)

        # Elegir el mejor y limpiar campo interno
        best = scored[0]
        best.pop("_score", None)
        final_products.append(best)

        top_scores = [(p["title"][:40], p["_score"]) for p in scored[:3]] if len(scored) >= 3 else []
        if top_scores:
            print(f"  [{category}] top: {top_scores}")

    print(f"Productos finales: {len(final_products)} / {len(ROUTINE_ORDER)} categorías")
    return final_products


# --- RUTA: DIAGNOSTICO SHOPIFY ---
@app.get("/debug/shopify/{tag}")
async def debug_shopify(tag: str):
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json"
    }
    tags_to_check = [tag, "grasa", "seca", "mixta", "sensible"]
    result = {}
    for t in tags_to_check:
        r = requests.get(f"{BASE_URL}/products.json?tag={t}&limit=10", headers=headers, timeout=10)
        products = r.json().get("products", []) if r.status_code == 200 else []
        result[t] = [{"title": p["title"], "tags": p.get("tags", "")} for p in products]
    return result


@app.get("/debug/collections")
async def debug_collections():
    """Ver qué productos hay en cada colección con sus tags y stock."""
    report = {}
    for category, handles in COLLECTIONS.items():
        report[category] = {}
        for handle in handles:
            products = get_products_by_collection(handle)
            report[category][handle] = [
                {
                    "title": p["title"],
                    "tags": p.get("tags", ""),
                    "stock": p["variants"][0].get("inventory_quantity", 0) if p.get("variants") else 0
                }
                for p in products[:10]
            ]
    return report


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

        analysis_data = extract_json(res_text)

        if not isinstance(analysis_data, dict):
            return {"error": "analysis_failed"}

        # 🔧 normalizar tipos
        analysis_data["elasticidad"] = int(analysis_data.get("elasticidad", 70))
        analysis_data["edad_piel"] = int(analysis_data.get("edad_piel", 30))

        print(
            f"Tipo: {analysis_data.get('tipo_piel')} | "
            f"H:{analysis_data.get('hidratacion')} "
            f"E:{analysis_data.get('elasticidad')} "
            f"S:{analysis_data.get('sensibilidad')} "
            f"Edad:{analysis_data.get('edad_piel')}"
        )

        # 🔥 FIX IMPORTANTE
        recommendations = get_shopify_recommendations(analysis_data)

        return {
            "result": analysis_data,
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