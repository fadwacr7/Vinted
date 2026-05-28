import os
import re
import base64
import json
from io import BytesIO
from pathlib import Path
from flask import Flask, request, jsonify, render_template
from anthropic import Anthropic
from PIL import Image
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT 1 — Analyse des photos (niveau vendeur professionnel)
# ─────────────────────────────────────────────────────────────────────────────
PROMPT_ANALYZE = """Tu es un vendeur PROFESSIONNEL Vinted avec 5 étoiles, expert en revente de mode.
Analyse TOUTES ces photos du même vêtement (face, dos, étiquettes, détails...).

Ton objectif : générer une annonce qui SE VEND EN MOINS DE 48H en ciblant le maximum d'acheteurs.

RÈGLES D'OR des vendeurs pro Vinted :
- Titre = Marque + Type + Couleur/Motif + Style + Taille (ex: "ZARA Robe midi fleurie bohème bleu T38 – État neuf")
- Description = accroche émotionnelle + détails précis + mensurations estimées + style + conseils
- Hashtags = mix marque + type + style + tendance + taille + occasion (minimum 10, maximum 15)
- Prix = réaliste par rapport au marché de l'occasion. IMPORTANT : si la pièce est vintage (design/coupe d'époque, étiquette ancienne, tissu d'époque), sa valeur dépasse souvent le prix neuf actuel de la marque — une pièce vintage d'une marque premium (Cacharel, Kenzo, Courrèges, Sonia Rykiel, etc.) vaut 30-150€+ sur Vinted selon l'état

Réponds UNIQUEMENT avec un JSON brut valide (zéro markdown, zéro backtick) :

{
  "titre": "Titre PRO : Marque + Type + Couleur + Style + Taille – État (70 car. max)",
  "categorie": "Catégorie Vinted exacte",
  "sous_categorie": "Sous-catégorie Vinted exacte",
  "marque": "Marque lue sur étiquette ou 'Sans marque'",
  "taille": "Taille exacte lue sur étiquette (36/38/S/M...)",
  "couleur_principale": "Couleur principale précise",
  "couleurs_secondaires": "Motif ou couleurs secondaires",
  "matiere": "Composition exacte si étiquette visible, sinon estimation honnête",
  "instructions_lavage": "Instructions lues sur étiquette, sinon 'Non lisible sur les photos'",
  "etat": "Neuf avec étiquette / Neuf sans étiquette / Très bon état / Bon état / Satisfaisant",
  "etat_detail": "Description précise de l'état basée sur les photos : coutures, tissu, étiquettes, défauts visibles",
  "defauts": "Défauts visibles et leur localisation précise, ou 'Aucun défaut visible'",
  "mensurations_estimees": "Estimation des mensurations selon la taille/coupe visible (ex: Tour poitrine ~88cm, Longueur ~95cm)",
  "description_accroche": "1 phrase émotionnelle et percutante qui donne envie d'acheter immédiatement",
  "description_complete": "Description PRO 180-220 mots avec : ✨ accroche → 📐 coupe et style → 🎨 couleur et matière → 👗 occasions de port → 📏 mensurations estimées → 🌀 entretien → 📦 expédition soignée. Utilise des emojis comme les vrais vendeurs pro.",
  "points_forts": ["Argument de vente 1 ultra précis", "Argument 2", "Argument 3", "Argument 4"],
  "hashtags": {
    "marque": ["#marque1", "#marque2"],
    "type": ["#typevêtement1", "#typevêtement2", "#typevêtement3"],
    "style": ["#style1", "#style2", "#style3"],
    "tendance": ["#tendance1", "#tendance2"],
    "taille": ["#taille38", "#tailleM"],
    "occasion": ["#occasion1", "#occasion2"]
  },
  "hashtags_flat": ["#ht1","#ht2","#ht3","#ht4","#ht5","#ht6","#ht7","#ht8","#ht9","#ht10","#ht11","#ht12"],
  "prix_ia_min": "Prix minimum réaliste en euros (entier uniquement, sans symbole)",
  "prix_ia_rec": "Prix recommandé pour vendre en moins de 48h (entier uniquement, sans symbole)",
  "prix_ia_max": "Prix maximum si acheteur moins pressé (entier uniquement, sans symbole)",
  "prix_ia_raisonnement": "Raisonnement précis : (1) tier de la marque aujourd'hui ET sa valeur vintage/collector si pièce ancienne, (2) prix neuf estimé, (3) coefficient état appliqué, (4) prime vintage si applicable (pièces vintage de marques premium valent souvent 1.5x à 3x leur prix occasion standard), (5) prix occasion réaliste sur Vinted.fr",
  "conseils_photos": ["Conseil photo 1 pour améliorer l'annonce", "Conseil 2", "Conseil 3"],
  "conseils_vente": ["Conseil vendeur pro 1", "Conseil 2", "Conseil 3", "Conseil 4"]
}"""

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT 2 — Prix IA réaliste (fallback si aucun prix marché trouvé)
# ─────────────────────────────────────────────────────────────────────────────
PROMPT_PRIX_FALLBACK = """Tu es un expert en valorisation de vêtements de seconde main.

Vêtement analysé :
- Marque : {marque}
- Type : {categorie} / {sous_categorie}
- Taille : {taille}
- Couleur : {couleur}
- Matière : {matiere}
- État : {etat}
- Défauts : {defauts}

Donne un prix de vente RÉALISTE et HONNÊTE pour Vinted.fr en France.

BARÈME DE RÉFÉRENCE (à adapter selon état) :
• Fast fashion (Shein, Primark, La Redoute basique) : 3-15€
• Entrée de gamme (Kiabi, C&A, Jules) : 4-18€
• Milieu de gamme (Zara, H&M, Mango, Bershka, Pull&Bear) : 6-30€
• Bon milieu (Cos, Arket, & Other Stories, Sandro basique) : 15-55€
• Premium (Maje, Sandro, Ba&sh, The Kooples) : 20-90€
• Luxe accessible (Michael Kors, Coach, Guess) : 25-120€
• Luxe (Gucci, Prada, Chanel, Dior) : 60-400€+
• Sport (Nike, Adidas, Lacoste) : 10-60€
• Streetwear (Supreme, Off-White, Palace) : 30-200€+

COEFFICIENTS PAR ÉTAT :
• Neuf avec étiquette : ×0.60 du prix neuf
• Neuf sans étiquette : ×0.45
• Très bon état : ×0.30-0.35
• Bon état : ×0.20-0.25
• Satisfaisant : ×0.10-0.15

Réponds UNIQUEMENT avec un JSON brut :
{{
  "prix_min": "entier",
  "prix_rec": "entier (pour vendre en moins d'1 semaine)",
  "prix_max": "entier (si acheteur patient)",
  "raisonnement": "Explication courte et honnête : tier marque → prix neuf estimé → coefficient état → prix occasion logique"
}}"""

# ─────────────────────────────────────────────────────────────────────────────
# Helpers image
# ─────────────────────────────────────────────────────────────────────────────
def compress_image(image_bytes: bytes, max_size: int = 1200) -> tuple[bytes, str]:
    img = Image.open(BytesIO(image_bytes))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > max_size:
        ratio = max_size / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=82, optimize=True)
    return buf.getvalue(), "image/jpeg"


# ─────────────────────────────────────────────────────────────────────────────
# Recherche prix marché
# ─────────────────────────────────────────────────────────────────────────────
def search_vinted_api(query: str) -> list:
    try:
        import requests as req
        r = req.get(
            "https://www.vinted.fr/api/v2/catalog/items",
            params={"search_text": query, "per_page": 24, "order": "relevance"},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Accept-Language": "fr-FR,fr;q=0.9",
                "Referer": "https://www.vinted.fr/",
            },
            timeout=8,
        )
        items = r.json().get("items", [])
        results = []
        for item in items[:20]:
            try:
                price = float(item.get("price_numeric") or item.get("price") or 0)
            except (ValueError, TypeError):
                continue
            if 1 < price < 2000:
                results.append({
                    "platform": "Vinted",
                    "prix": round(price, 2),
                    "titre": (item.get("title") or "")[:60],
                    "marque": item.get("brand_title") or "",
                    "taille": item.get("size_title") or "",
                    "url": "https://www.vinted.fr" + (item.get("url") or ""),
                })
        return results
    except Exception:
        return []


def search_via_duckduckgo(query: str, platform: str = "vinted.fr") -> list:
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(f'"{query}" prix site:{platform}', max_results=8, region="fr-fr"):
                text = (r.get("body") or "") + " " + (r.get("title") or "")
                prices = re.findall(r"(\d+(?:[.,]\d+)?)\s*€", text)
                for pm in prices[:1]:
                    try:
                        price = float(pm.replace(",", "."))
                        if 1 < price < 2000:
                            plat = "Vinted" if "vinted" in platform else "LeBonCoin"
                            results.append({
                                "platform": plat,
                                "prix": round(price, 2),
                                "titre": (r.get("title") or "")[:60],
                                "marque": "",
                                "taille": "",
                                "url": r.get("href") or "",
                            })
                            break
                    except ValueError:
                        pass
        return results
    except Exception:
        return []


def get_market_prices(marque: str, categorie: str, couleur: str = "") -> dict:
    brand = marque if marque.lower() not in ("sans marque", "non visible", "", "inconnue") else ""
    parts = [p for p in [brand, categorie, couleur] if p]
    query = " ".join(parts[:3])
    if not query.strip():
        return {"prices": [], "stats": None, "nb": 0}

    prices_list = search_vinted_api(query)
    if len(prices_list) < 4:
        prices_list += search_via_duckduckgo(query, "vinted.fr")
    prices_list += search_via_duckduckgo(query, "leboncoin.fr")

    # Dédoublonnage
    seen, unique = set(), []
    for p in prices_list:
        k = p["url"] or p["titre"]
        if k not in seen:
            seen.add(k)
            unique.append(p)

    vals = sorted(p["prix"] for p in unique if p["prix"] > 0)
    if len(vals) < 2:
        return {"prices": unique[:12], "stats": None, "nb": len(unique)}

    n = len(vals)
    return {
        "prices": unique[:12],
        "stats": {
            "nb": n,
            "min": vals[0],
            "max": vals[-1],
            "median": round(vals[n // 2], 2),
            "q1": round(vals[max(0, n // 4)], 2),
            "q3": round(vals[min(n - 1, 3 * n // 4)], 2),
        },
        "nb": len(unique),
    }


def calc_price_from_market(stats: dict, etat: str) -> dict:
    """Prix basé sur les données réelles du marché."""
    etat_l = etat.lower()
    if "étiquette" in etat_l:   mult = 1.00
    elif "neuf" in etat_l:       mult = 0.85
    elif "très bon" in etat_l or "tres bon" in etat_l: mult = 0.70
    elif "bon" in etat_l:        mult = 0.55
    else:                        mult = 0.40

    rec = max(1, round(stats["median"] * mult))
    mn  = max(1, round(stats["q1"]    * mult * 0.85))
    mx  = max(1, round(stats["q3"]    * mult * 1.15))
    return {
        "prix_suggere":       str(rec),
        "prix_min":           str(mn),
        "prix_max":           str(mx),
        "prix_source":        "marche",
        "prix_justification": (
            f"Prix calculé sur {stats['nb']} annonces réelles Vinted & LeBonCoin "
            f"(médiane marché : {int(stats['median'])}€, "
            f"fourchette : {int(stats['q1'])}€–{int(stats['q3'])}€). "
            f"Coefficient état appliqué : ×{mult} pour « {etat} »."
        ),
    }


def get_ai_price(item: dict) -> dict:
    """Prix estimé par Claude quand aucune donnée marché disponible."""
    prompt = PROMPT_PRIX_FALLBACK.format(
        marque=item.get("marque", "Sans marque"),
        categorie=item.get("categorie", "Vêtement"),
        sous_categorie=item.get("sous_categorie", ""),
        taille=item.get("taille", "Non précisée"),
        couleur=item.get("couleur_principale", ""),
        matiere=item.get("matiere", ""),
        etat=item.get("etat", "Bon état"),
        defauts=item.get("defauts", "Aucun"),
    )
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
    if "```" in raw:
        raw = raw[:raw.rfind("```")]
    data = json.loads(raw.strip())
    return {
        "prix_suggere":       str(data.get("prix_rec", "—")),
        "prix_min":           str(data.get("prix_min", "—")),
        "prix_max":           str(data.get("prix_max", "—")),
        "prix_source":        "ia",
        "prix_justification": data.get("raisonnement", ""),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    files = request.files.getlist("images")
    if not files or all(f.filename == "" for f in files):
        return jsonify({"error": "Aucune image fournie"}), 400

    SLOT_LABELS = ["face", "dos", "étiquette", "détail", "défaut", "autre"]
    allowed = {"png", "jpg", "jpeg", "webp", "gif"}

    # ── Étape 1 : préparer le contenu pour Claude ────────────────────
    content = []
    nb = 0
    for i, file in enumerate(files):
        if file.filename == "":
            continue
        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in allowed:
            continue
        raw = file.read()
        img_bytes, media_type = compress_image(raw)
        b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
        label = SLOT_LABELS[i] if i < len(SLOT_LABELS) else f"photo {i+1}"
        content.append({"type": "text", "text": f"Photo {i+1} ({label}) :"})
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        })
        nb += 1

    if nb == 0:
        return jsonify({"error": "Aucune image valide"}), 400

    content.append({"type": "text", "text": PROMPT_ANALYZE})

    try:
        # ── Étape 2 : analyse IA complète ───────────────────────────
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2500,
            messages=[{"role": "user", "content": content}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
        if "```" in raw:
            raw = raw[:raw.rfind("```")]
        item = json.loads(raw.strip())
        item["nb_photos"] = nb

    except json.JSONDecodeError as e:
        return jsonify({"error": f"L'IA n'a pas retourné un JSON valide : {e}"}), 500
    except Exception as e:
        return jsonify({"error": f"Erreur lors de l'analyse IA : {str(e)}"}), 500

    try:
        # ── Étape 3 : recherche prix marché ─────────────────────────
        market = get_market_prices(
            marque=item.get("marque", ""),
            categorie=item.get("categorie", ""),
            couleur=item.get("couleur_principale", ""),
        )
        item["market_data"] = market
    except Exception:
        item["market_data"] = {"prices": [], "stats": None, "nb": 0}

    try:
        # ── Étape 4 : calcul prix ────────────────────────────────────
        if item.get("market_data", {}).get("stats"):
            item.update(calc_price_from_market(
                item["market_data"]["stats"], item.get("etat", "Bon état")
            ))
        else:
            # Priorité aux prix déjà estimés par Claude lors de l'analyse photos
            # (contexte complet : photos + vintage + état réel)
            rec = item.get("prix_ia_rec", "")
            mn  = item.get("prix_ia_min", "")
            mx  = item.get("prix_ia_max", "")
            just = item.get("prix_ia_raisonnement", "")
            if rec and str(rec).lstrip("-").isdigit() and int(str(rec)) > 0:
                item.update({
                    "prix_suggere":       str(rec),
                    "prix_min":           str(mn) if str(mn).lstrip("-").isdigit() else str(rec),
                    "prix_max":           str(mx) if str(mx).lstrip("-").isdigit() else str(rec),
                    "prix_source":        "ia",
                    "prix_justification": just or "Prix estimé par l'IA lors de l'analyse des photos.",
                })
            else:
                item.update(get_ai_price(item))
    except Exception as e:
        # Dernier recours : prix par défaut safe
        item.setdefault("prix_suggere", "10")
        item.setdefault("prix_min", "5")
        item.setdefault("prix_max", "20")
        item.setdefault("prix_source", "ia")
        item.setdefault("prix_justification", "Prix estimé par défaut. Vérifiez manuellement.")

    return jsonify(item)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
