import os
import re
import uuid
import requests
import json
import hashlib
import uvicorn
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from google.genai import types

# --- FIREBASE ---
import firebase_admin
from firebase_admin import credentials, firestore

if not firebase_admin._apps:
    cred = credentials.Certificate(os.getenv("FIREBASE_CREDENTIALS_PATH", "serviceAccountKey.json"))
    firebase_admin.initialize_app(cred)

db = firestore.client()

app = FastAPI()

# --- CONFIGURACION — nombres alineados al .env ---
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY")
SHOPIFY_TOKEN      = os.getenv("SHOPIFY_ACCESS_TOKEN")
SHOP_NAME          = os.getenv("SHOPIFY_SHOP_NAME")
API_VER            = os.getenv("SHOPIFY_API_VERSION", "2024-10")
BASE_URL           = f"https://{SHOP_NAME}.myshopify.com/admin/api/{API_VER}"

MAILCHIMP_API_KEY  = os.getenv("MAILCHIMP_API_KEY")
MAILCHIMP_DC       = os.getenv("MAILCHIMP_DC", "us7")
MAILCHIMP_LIST_ID  = os.getenv("MAILCHIMP_AUDIENCE_ID")
MAILCHIMP_BASE_URL = f"https://{MAILCHIMP_DC}.api.mailchimp.com/3.0"

client = genai.Client(
    api_key=GEMINI_API_KEY,
)

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


# ─────────────────────────────────────────────
# FIRESTORE HELPERS
# ─────────────────────────────────────────────

def _new_id() -> str:
    return str(uuid.uuid4())


def _asegurar_usuario(user_id: str, email: str = "") -> None:
    """Crea el documento de usuario en Firestore si no existe todavía."""
    user_ref = db.collection("usuarios").document(user_id)
    if not user_ref.get().exists:
        user_ref.set({
            "perfil": {
                "nombre": "",
                "email": email,
                "skin_type_latest": None,
                "skin_concerns_latest": [],
            },
            "lealtad": {
                "puntos": 0,
                "puntos_acumulados_total": 0,
                "tier": "bronze",
            },
            "modelo_ml": {
                "ltv_estimado": 0,
                "probabilidad_compra": 0.5,
                "sensibilidad_precio": 0.5,
                "segmento_dinamico": None,
                "ultima_interaccion": firestore.SERVER_TIMESTAMP,
            },
            "metadata": {
                "created_at": firestore.SERVER_TIMESTAMP,
                "last_analysis_id": None,
                "last_purchase_date": None,
                "total_purchases": 0,
            }
        })
        print(f"✅ Usuario creado en Firestore: {user_id}")


def _guardar_analisis(user_id: str, analysis_data: dict, products: list) -> str:
    """
    Guarda el análisis completo en la subcolección usuarios/{user_id}/analisis.
    Devuelve el analysis_id generado.
    """
    analysis_id = _new_id()

    # Normalizar concerns desde los puntos_clave del análisis
    concerns = []
    puntos = " ".join(analysis_data.get("puntos_clave", [])).lower()
    if "acn" in puntos or "grano" in puntos:
        concerns.append("acne")
    if "poro" in puntos:
        concerns.append("poros_dilatados")
    if "mancha" in puntos:
        concerns.append("manchas")
    if "hidrat" in puntos or "seca" in puntos:
        concerns.append("deshidratacion")
    if "rojez" in puntos or "irritad" in puntos:
        concerns.append("sensibilidad")

    resultados = {
        "skin_type":   analysis_data.get("tipo_piel_tag"),
        "skin_label":  analysis_data.get("tipo_piel"),
        "concerns":    concerns,
        "scores": {
            "hidratacion":  analysis_data.get("hidratacion", ""),
            "elasticidad":  analysis_data.get("elasticidad", 0),
            "sensibilidad": analysis_data.get("sensibilidad", ""),
            "edad_piel":    analysis_data.get("edad_piel", 0),
        },
        "analisis_texto":  analysis_data.get("analisis", ""),
        "puntos_clave":    analysis_data.get("puntos_clave", []),
        "rutina_sugerida": analysis_data.get("rutina_sugerida", ""),
    }

    # Guardar en subcolección
    analisis_ref = (
        db.collection("usuarios")
          .document(user_id)
          .collection("analisis")
          .document(analysis_id)
    )
    analisis_ref.set({
        "analysis_id":       analysis_id,
        "resultados":        resultados,
        "productos_sugeridos": [
            {
                "title":      p.get("title"),
                "category":   p.get("category"),
                "variant_id": p.get("variant_id"),
                "price":      p.get("price"),
            }
            for p in products
        ],
        "algoritmo_version": "v1",
        "timestamp":         firestore.SERVER_TIMESTAMP,
    })

    # Actualizar perfil raíz del usuario
    db.collection("usuarios").document(user_id).update({
        "perfil.skin_type_latest":    resultados["skin_type"],
        "perfil.skin_concerns_latest": concerns,
        "metadata.last_analysis_id":  analysis_id,
        "modelo_ml.ultima_interaccion": firestore.SERVER_TIMESTAMP,
    })

    # Registrar evento para el learning loop
    db.collection("eventos_usuario").document(_new_id()).set({
        "event_id":   _new_id(),
        "user_id":    user_id,
        "event_name": "analysis_completed",
        "properties": {
            "skin_type":        resultados["skin_type"],
            "concerns":         concerns,
            "analysis_id":      analysis_id,
            "productos_count":  len(products),
        },
        "context": {"platform": "web", "algoritmo_version": "v1"},
        "timestamp": firestore.SERVER_TIMESTAMP,
    })

    print(f"✅ Análisis guardado en Firestore: {analysis_id} → usuario {user_id}")
    return analysis_id


def _acumular_puntos_simple(user_id: str, puntos: int, motivo: str, metadata: dict = None) -> None:
    """Versión simplificada (sin transacción) para acumular puntos."""
    user_ref = db.collection("usuarios").document(user_id)
    snapshot = user_ref.get()
    if not snapshot.exists:
        return

    saldo_actual   = snapshot.get("lealtad.puntos") or 0
    acumulado_total = snapshot.get("lealtad.puntos_acumulados_total") or 0
    nuevo_saldo    = saldo_actual + puntos
    nuevo_total    = acumulado_total + max(puntos, 0)

    update_data = {
        "lealtad.puntos":                nuevo_saldo,
        "lealtad.puntos_acumulados_total": nuevo_total,
        "modelo_ml.ultima_interaccion":  firestore.SERVER_TIMESTAMP,
    }

    if nuevo_total >= 5000:
        update_data["lealtad.tier"] = "platinum"
    elif nuevo_total >= 2000:
        update_data["lealtad.tier"] = "gold"
    elif nuevo_total >= 500:
        update_data["lealtad.tier"] = "silver"

    user_ref.update(update_data)

    tx_ref = user_ref.collection("transacciones_lealtad").document(_new_id())
    tx_ref.set({
        "tipo":             "earn" if puntos >= 0 else "redeem",
        "puntos":           puntos,
        "saldo_resultante": nuevo_saldo,
        "motivo":           motivo,
        "metadata":         metadata or {},
        "timestamp":        firestore.SERVER_TIMESTAMP,
    })
    print(f"✅ Puntos acumulados: +{puntos} → usuario {user_id} (nuevo saldo: {nuevo_saldo})")

# --- MODELOS ---
class EmailSubscription(BaseModel):
    email: str
    skin_type: str
    skin_tag: str
    products: list
    analisis: str = ''
    hidratacion: str = ''
    sensibilidad: str = ''
    elasticidad: int = 0
    edad_piel: int = 0
    puntos_clave: list = []
    rutina_sugerida: str = ''
    score: int = 0
    analysis_id: str = ''   # ID del análisis pendiente generado en /analyze


# --- MAILCHIMP ---
def subscribe_to_mailchimp(
    email: str,
    skin_type: str,
    skin_tag: str,
    products: list,
    analisis: str = '',
    hidratacion: str = '',
    sensibilidad: str = '',
    elasticidad: int = 0,
    edad_piel: int = 0,
    puntos_clave: list = None,
    rutina_sugerida: str = '',
    score: int = 0
):
    headers = {
        "Authorization": f"Bearer {MAILCHIMP_API_KEY}",
        "Content-Type": "application/json"
    }

    puntos_clave  = puntos_clave or []
    email_hash    = hashlib.md5(email.lower().encode()).hexdigest()
    product_names = " | ".join([p.get("title", "") for p in products[:4]])
    puntos_str    = " | ".join(puntos_clave[:3])
    member_url    = f"{MAILCHIMP_BASE_URL}/lists/{MAILCHIMP_LIST_ID}/members/{email_hash}"

    merge_fields = {
        "SKIN_TYPE":  skin_type,
        "SKIN_TAG":   skin_tag,
        "PRODUCTS":   product_names,
        "ANALISIS":   analisis[:500] if analisis else '',
        "HIDRAT":     hidratacion,
        "SENSI":      sensibilidad,
        "ELAST":      str(elasticidad) if elasticidad else '',
        "EDAD_PIEL":  str(edad_piel) if edad_piel else '',
        "PUNTOS":     puntos_str,
        "RUTINA":     rutina_sugerida[:400] if rutina_sugerida else '',
        "SCORE":      str(score) if score else '',
    }

    tags_to_apply = [
        {"name": f"piel-{skin_tag}",   "status": "active"},
        {"name": "analizador-ia",       "status": "active"},
        {"name": "analisis-completado", "status": "active"},
    ]
    if hidratacion.lower() == 'baja':
        tags_to_apply.append({"name": "hidratacion-baja", "status": "active"})
    if sensibilidad.lower() == 'alta':
        tags_to_apply.append({"name": "piel-sensible", "status": "active"})
    if edad_piel and edad_piel >= 30:
        tags_to_apply.append({"name": "anti-edad", "status": "active"})
    if score and score < 60:
        tags_to_apply.append({"name": "score-bajo", "status": "active"})

    # Verificar estado actual del contacto
    check = requests.get(member_url, headers=headers)
    current_status = None
    if check.status_code == 200:
        current_status = check.json().get("status")

    print(f"Mailchimp: estado actual de {email} → {current_status}")

    # Definir nuevo status:
    # - Si no existe (None), pending o cleaned → suscribir
    # - Si ya está unsubscribed → respetar, no forzar
    # - Si ya está subscribed → mantener
    if current_status in (None, "pending", "cleaned", "transactional"):
        new_status = "subscribed"
    elif current_status == "unsubscribed":
        new_status = "unsubscribed"
    else:
        new_status = current_status

    # UPSERT con status explícito
    res = requests.put(
        member_url,
        headers=headers,
        json={
            "email_address": email,
            "status":        new_status,
            "status_if_new": "subscribed",
            "merge_fields":  merge_fields,
        }
    )

    print(f"Mailchimp PUT status code: {res.status_code}")
    print(f"Mailchimp PUT response: {res.text[:500]}")

    if res.status_code in [200, 204]:
        # Aplicar tags por separado
        tag_res = requests.post(
            f"{member_url}/tags",
            headers=headers,
            json={"tags": tags_to_apply}
        )
        print(f"Mailchimp tags status: {tag_res.status_code}")
        action = "creado" if res.json().get("status") == "subscribed" and current_status is None else "actualizado"
        print(f"Mailchimp: contacto {action} ({email}) tag=piel-{skin_tag} score={score}")
        return {"status": "subscribed", "message": f"Contacto {action}"}
    else:
        print(f"Mailchimp error {res.status_code}: {res.text}")
        return {"status": "error", "message": res.text}


# --- COLECCIONES SHOPIFY ---
COLLECTIONS = {
    "oil-cleanser": ["limpiadores-oleosos-desmaquillantes"],
    "foam-cleanser": ["limpiador-en-espuma"],
    "toner":        ["tonicos"],
    "serum":        ["serum"],
    "moisturizer":  ["cremas-y-lociones"],
    "sunscreen":    ["protector-solar"]
}


def extract_json(text):
    try:
        return json.loads(text)
    except:
        pass

    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except:
        pass

    print("⚠️ No se pudo parsear JSON")
    return {}


def extract_skin_needs(analysis):
    needs = []

    hidratacion = analysis.get("hidratacion", "").lower()
    if hidratacion in ["baja", "media"]:
        needs.append("hidratacion")

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
        collection_id   = None
        collection_type = None

        res = requests.get(
            f"{BASE_URL}/custom_collections.json?handle={handle}",
            headers=headers,
            timeout=10
        )
        if res.status_code == 200:
            custom = res.json().get("custom_collections", [])
            if custom:
                collection_id   = custom[0]["id"]
                collection_type = "custom"

        if not collection_id:
            res = requests.get(
                f"{BASE_URL}/smart_collections.json?handle={handle}",
                headers=headers,
                timeout=10
            )
            if res.status_code == 200:
                smart = res.json().get("smart_collections", [])
                if smart:
                    collection_id   = smart[0]["id"]
                    collection_type = "smart"

        if not collection_id:
            print(f"  ❌ Colección '{handle}' NO encontrada (ni custom ni smart)")
            return []

        print(f"  ✅ Colección '{handle}' [{collection_type}] id={collection_id}")

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
ROUTINE_ORDER = [
    "oil-cleanser",
    "foam-cleanser",
    "toner",
    "serum",
    "moisturizer",
    "sunscreen",
]

SKIN_TYPE_COMPATIBILITY = {
    "grasa":    ["grasa", "mixta", "normal"],
    "mixta":    ["mixta", "grasa", "normal"],
    "seca":     ["seca", "normal", "sensible"],
    "sensible": ["sensible", "seca", "normal"],
    "normal":   ["normal", "mixta", "seca", "grasa"],
}


def score_product(p, tipo_piel, needs, category):
    tags  = [t.lower().strip() for t in p.get("tags", "").split(",")]
    score = 0

    compatible = SKIN_TYPE_COMPATIBILITY.get(tipo_piel, [tipo_piel])
    if tipo_piel and tipo_piel in tags:
        score += 20
    elif any(t in tags for t in compatible):
        score += 10
    elif "todo-tipo" in tags or "all-skin" in tags or "all skin" in tags:
        score += 8

    for need in needs:
        if need in tags:
            score += 5

    if "best-seller" in tags or "bestseller" in tags:
        score += 8
    if "destacado" in tags or "featured" in tags:
        score += 4

    variants = p.get("variants", [])
    if variants:
        v   = variants[0]
        qty = v.get("inventory_quantity", 0)
        if qty > 20:
            score += 3
        elif qty > 5:
            score += 1

    if p.get("image") or p.get("images"):
        score += 2

    return score


def build_product_entry(p, category):
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

        all_products = []
        for handle in handles:
            all_products.extend(get_products_by_collection(handle))

        if not all_products:
            print(f"⚠️  Sin productos en categoría: {category}")
            continue

        seen_ids        = set()
        unique_products = []
        for p in all_products:
            pid = p.get("id")
            if pid not in seen_ids:
                seen_ids.add(pid)
                unique_products.append(p)

        def is_available(p):
            variants = p.get("variants", [])
            if not variants:
                return False
            v = variants[0]
            if v.get("inventory_management") in (None, ""):
                return True
            if v.get("inventory_policy") == "continue":
                return True
            return v.get("inventory_quantity", 0) > 0

        with_stock = [p for p in unique_products if is_available(p)]

        if not with_stock:
            sample = unique_products[:2]
            for sp in sample:
                v = sp.get("variants", [{}])[0]
                print(f"  ⚠️  Sin stock: '{sp['title'][:35]}' "
                      f"inv_mgmt={v.get('inventory_management')} "
                      f"qty={v.get('inventory_quantity')} policy={v.get('inventory_policy')}")
            print(f"⚠️  Sin stock en categoría: {category}")
            continue

        scored = []
        for p in with_stock:
            s     = score_product(p, tipo_piel, needs, category)
            entry = build_product_entry(p, category)
            if entry:
                entry["_score"] = s
                scored.append(entry)

        if not scored:
            continue

        scored.sort(key=lambda x: x["_score"], reverse=True)

        top_scores = [(p["title"][:40], p["_score"]) for p in scored[:3]]
        print(f"  [{category}] top: {top_scores}")

        best = scored[0]
        best.pop("_score", None)
        final_products.append(best)

    print(f"Productos finales: {len(final_products)} / {len(ROUTINE_ORDER)} categorías")
    return final_products


# --- RUTA: DIAGNOSTICO GEMINI ---
@app.get("/debug/gemini")
async def debug_gemini():
    try:
        available = []
        for m in client.models.list():
            if hasattr(m, 'supported_actions') and 'generateContent' in (m.supported_actions or []):
                available.append(m.name)
            elif hasattr(m, 'name') and 'flash' in m.name.lower():
                available.append(m.name)

        results     = {}
        test_models = [
            'gemini-2.5-flash-preview-04-17',
            'gemini-2.0-flash',
            'gemini-1.5-flash',
            'gemini-1.5-flash-8b',
        ]
        for model_name in test_models:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents="Responde solo: ok"
                )
                results[model_name] = "ok" if response and response.text else "sin respuesta"
            except Exception as e:
                err = str(e)
                if "429" in err or "quota" in err.lower():
                    results[model_name] = "quota excedida"
                else:
                    results[model_name] = f"error: {err[:80]}"

        return {"available_models": available, "quota_check": results}
    except Exception as e:
        return {"error": str(e)}


# --- RUTA: DIAGNOSTICO SHOPIFY ---
@app.get("/debug/shopify/{tag}")
async def debug_shopify(tag: str):
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json"
    }
    tags_to_check = [tag, "grasa", "seca", "mixta", "sensible"]
    result        = {}
    for t in tags_to_check:
        r              = requests.get(f"{BASE_URL}/products.json?tag={t}&limit=10", headers=headers, timeout=10)
        products       = r.json().get("products", []) if r.status_code == 200 else []
        result[t]      = [{"title": p["title"], "tags": p.get("tags", "")} for p in products]
    return result


@app.get("/debug/collections")
async def debug_collections():
    """Ver qué productos hay en cada colección con sus tags y stock."""
    report = {}
    for category, handles in COLLECTIONS.items():
        report[category] = {}
        for handle in handles:
            products             = get_products_by_collection(handle)
            report[category][handle] = [
                {
                    "title": p["title"],
                    "tags":  p.get("tags", ""),
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

        MODEL_PRIORITY = [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
        ]

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

        response   = None
        last_error = None

        for model_name in MODEL_PRIORITY:
            try:
                print(f"Intentando con modelo: {model_name}")
                response = client.models.generate_content(
                    model=model_name,
                    contents=[
                        prompt,
                        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
                    ]
                )
                if response and response.text:
                    print(f"✅ Respuesta ok con {model_name}")
                    break
            except Exception as model_err:
                last_error = model_err
                err_str    = str(model_err)
                if any(x in err_str.lower() for x in ["429", "quota", "exceeded", "404", "not found"]):
                    print(f"⚠️ Error en {model_name}, probando siguiente...")
                    continue
                else:
                    raise

        if not response or not response.text:
            raise Exception(f"Todos los modelos fallaron. Último error: {last_error}")

        res_text = response.text.strip()
        if "```json" in res_text:
            res_text = res_text.split("```json")[1].split("```")[0].strip()
        elif "```" in res_text:
            res_text = res_text.split("```")[1].split("```")[0].strip()

        analysis_data = extract_json(res_text)

        if not isinstance(analysis_data, dict):
            return {"error": "analysis_failed"}

        analysis_data["elasticidad"] = int(analysis_data.get("elasticidad", 70))
        analysis_data["edad_piel"]   = int(analysis_data.get("edad_piel", 30))

        print(
            f"Tipo: {analysis_data.get('tipo_piel')} | "
            f"H:{analysis_data.get('hidratacion')} "
            f"E:{analysis_data.get('elasticidad')} "
            f"S:{analysis_data.get('sensibilidad')} "
            f"Edad:{analysis_data.get('edad_piel')}"
        )

        recommendations = get_shopify_recommendations(analysis_data)

        # ── FIRESTORE: contar análisis totales para métrica de funnel ──
        analysis_id = _new_id()
        try:
            db.collection("metricas").document("funnel").set({
                "total_analisis": firestore.Increment(1),
                "updated_at":     firestore.SERVER_TIMESTAMP,
            }, merge=True)
            print(f"✅ Funnel: total_analisis +1")
        except Exception as fe:
            print(f"⚠️  Firestore error en /analyze (no crítico): {fe}")

        return {
            "result":      analysis_data,
            "products":    recommendations,
            "analysis_id": analysis_id,   # el frontend lo envía en /subscribe
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
            products=data.products,
            analisis=data.analisis,
            hidratacion=data.hidratacion,
            sensibilidad=data.sensibilidad,
            elasticidad=data.elasticidad,
            edad_piel=data.edad_piel,
            puntos_clave=data.puntos_clave,
            rutina_sugerida=data.rutina_sugerida,
            score=data.score
        )

        # ── FIRESTORE: guardar análisis y actualizar métricas de funnel ──
        try:
            user_id = hashlib.md5(data.email.lower().encode()).hexdigest()

            # 1. Crear usuario si no existe
            _asegurar_usuario(user_id, email=data.email)

            # 2. Construir analysis_data desde los campos del subscribe
            analysis_data = {
                "tipo_piel_tag":   data.skin_tag,
                "tipo_piel":       data.skin_type,
                "analisis":        data.analisis,
                "hidratacion":     data.hidratacion,
                "sensibilidad":    data.sensibilidad,
                "elasticidad":     data.elasticidad,
                "edad_piel":       data.edad_piel,
                "puntos_clave":    data.puntos_clave,
                "rutina_sugerida": data.rutina_sugerida,
            }

            # 3. Guardar análisis bajo el usuario
            saved_id = _guardar_analisis(user_id, analysis_data, data.products)

            # 4. Dar puntos (bienvenida solo la primera vez)
            total_analisis = len(
                list(db.collection("usuarios").document(user_id)
                     .collection("analisis").limit(2).stream())
            )
            if total_analisis <= 1:
                _acumular_puntos_simple(user_id, 200, "bienvenida")
                _acumular_puntos_simple(user_id, 50, "analisis_completado",
                                        metadata={"analysis_id": saved_id})
            else:
                _acumular_puntos_simple(user_id, 50, "analisis_completado",
                                        metadata={"analysis_id": saved_id})

            # 5. Incrementar conversiones en el funnel
            db.collection("metricas").document("funnel").set({
                "total_conversiones": firestore.Increment(1),
                "updated_at":         firestore.SERVER_TIMESTAMP,
            }, merge=True)

            print(f"✅ Firestore: usuario {user_id} → análisis {saved_id} | funnel conversión +1")

        except Exception as fe:
            print(f"⚠️  Firestore error en /subscribe (no crítico): {fe}")

        return result

    except Exception as e:
        print(f"Error suscripcion: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# --- INICIO para Cloud Run ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)