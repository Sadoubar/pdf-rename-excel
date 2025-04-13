import streamlit as st
import os
import zipfile
import tempfile
import shutil
import re
import fitz  # PyMuPDF
import time
import pandas as pd # Ajout pour Excel
import io # Ajout pour gérer le fichier Excel en mémoire

# --- Configuration Streamlit ---
st.set_page_config(
    page_title="Extracteur PDF", # Titre mis à jour
    page_icon="📄",
    layout="wide"
)

# --- Sidebar ---
logo_url = "https://img.freepik.com/photos-premium/arbre-champ-contre-ciel_1048944-22099641.jpg?semt=ais_hybrid&w=740" # Changement d'image
st.sidebar.image(logo_url, width=750)
st.sidebar.title("Options & Infos")
st.sidebar.info("""
    ℹ️ **Mode d'Extraction:**
    Extraction locale des données des PDF via Regex.
    Recherche les champs spécifiques des rapports Hej-ABd.
    Génère un fichier Excel récapitulatif.
    """)

# --- Titre Principal ---
st.title("📄 Extracteur & Renommeur de Rapports PDF") # Titre mis à jour
st.markdown("Optimisé par H-A :)")

st.divider()

# --- Instructions Utilisateur Clarifiées ---
st.markdown("### Comment utiliser cet outil :")
st.markdown("""
1.  **Déposez vos fichiers** dans la zone ci-dessous :
    *   Fichiers PDF individuels (nommés avec 'REFERENCE' ou similaire).
    *   **OU** une archive ZIP contenant vos PDF.
2.  Cliquez sur **"🚀 Lancer le Traitement"**.
3.  **Patientez** pendant l'analyse, le renommage et l'extraction des données.
4.  **Consultez le résumé** et **téléchargez** l'archive ZIP contenant les PDF renommés et le fichier Excel récapitulatif.
""")

st.divider()

# --- Fonctions ---

def safe_search(pattern, text, group_index=1, default_value=""):
    """Effectue une recherche regex et retourne le groupe ou une valeur par défaut."""
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if match and len(match.groups()) >= group_index:
        return match.group(group_index).strip().replace('\n', ' ') # Remplace les sauts de ligne par des espaces
    return default_value

def extraire_donnees_pdf(pdf_path):
    """Extrait les données structurées d'un PDF Greenprime."""
    data = {}
    doc = None
    nom_fichier = os.path.basename(pdf_path)

    try:
        doc = fitz.open(pdf_path)
        text_page1 = ""
        text_page2 = ""
        if len(doc) > 0:
            text_page1 = doc.load_page(0).get_text("text")
        if len(doc) > 1:
            text_page2 = doc.load_page(1).get_text("text")
        else:
             # Si pas de page 2, on essaie quand même de trouver les infos sur la page 1
             text_page2 = text_page1

        # Combiner texte peut aider si un champ est coupé entre pages (peu probable ici)
        # full_text = text_page1 + "\n" + text_page2

        # --- Extraction Page 1 ---
        data["Reference Rapport"] = safe_search(r"Référence du rapport\s+(.*?)(?:\n|$)", text_page1)
        data["FOS"] = safe_search(r"BAR-TH-\d+", text_page1 + text_page2) # Recherche FOS sur les deux pages

        # --- Extraction Page 2 (ou Page 1 si unique) ---
        # Utiliser text_page2 car c'est là que la plupart des infos sont attendues
        data["Adresse Travaux"] = safe_search(r"Adresse des travaux\s+(.*?)\nNom du bénéficiaire", text_page2)
        # Si le pattern ci-dessus échoue (car Nom du bénéficiaire n'est pas juste après), essayer une version plus simple
        if not data["Adresse Travaux"]:
             data["Adresse Travaux"] = safe_search(r"Adresse des travaux\s+(.*?)(?:\n\s*\n|\n[A-Z])", text_page2) # Essaye d'arrêter avant un double saut de ligne ou une nouvelle ligne commençant par une majuscule


        data["Nom Beneficiaire"] = safe_search(r"Nom du bénéficiaire\s+(.*?)(?:\n|$)", text_page2)
        data["Raison Sociale Professionnel"] = safe_search(r"Raison sociale du professionnel\s+(.*?)(?:\n|$)", text_page2)

        data["Beneficiaire Joint"] = safe_search(r"Bénéficiaire joint\s+(OUI|NON)", text_page2)
        data["Telephone Errone"] = safe_search(r"Numéro de téléphone erroné\s+(OUI|NON)", text_page2)
        data["Controle Realise"] = safe_search(r"Contrôle réalisé\s+(OUI|NON)", text_page2)
        data["Date Controle"] = safe_search(r"Date du contrôle\s+([\d/]+)", text_page2)

        data["Systeme Regulation Installe"] = safe_search(r"pièce par pièce installé\s+(OUI|NON)", text_page2) # Simplifié
        data["Reception Consignes Emetteurs"] = safe_search(r"température de consigne\s+(OUI|NON)", text_page2) # Simplifié
        data["Commentaire Non Reception"] = safe_search(r"n'est pas assurée\s+([^\n]*)", text_page2) # Capture la ligne après "assurée"
        data["Absence Non Qualite Manifeste"] = safe_search(r"détectée par le bénéficiaire\s+(OUI|NON)", text_page2) # Simplifié
        data["Commentaire Non Qualite Relevee"] = safe_search(r"non-qualité relevée\s+([^\n]*)", text_page2) # Capture la ligne après "relevée"

        # Conclusion - Recherche le mot clé spécifique
        if "SATISFAISANT" in text_page2:
            data["Conclusion Controle"] = "SATISFAISANT"
        elif "NON SATISFAISANT" in text_page2:
             data["Conclusion Controle"] = "NON SATISFAISANT"
        else:
             # Essayer de capturer après le label si les mots clés ne sont pas trouvés
             data["Conclusion Controle"] = safe_search(r"Conclusion du contrôle\s+([^\n]*)", text_page2)


        # Nettoyage final (enlever les espaces superflus)
        for key, value in data.items():
             if isinstance(value, str):
                 data[key] = ' '.join(value.split())


        # Vérifier si des données essentielles (comme la référence) ont été trouvées
        if not data.get("Reference Rapport"):
            st.warning(f"⚠️ Référence non trouvée dans {nom_fichier}. Extraction de données peut être incomplète.")
            # On retourne quand même ce qu'on a trouvé, mais la référence est clé
            # return None # Optionnel: considérer l'extraction comme échouée si la ref manque

        return data

    except Exception as e:
        st.error(f"❌ Erreur extraction données PDF '{nom_fichier}' : {type(e).__name__} - {e}")
        return None # Retourne None en cas d'erreur majeure
    finally:
        if doc:
            try: doc.close()
            except: pass


def traiter_pdf_et_extraire(pdf_path, dossier_sortie):
    """
    Traite un PDF: renomme/copie ET extrait les données.
    Retourne: status, nom_original, nouveau_nom, donnees_extraites
    Status: success, skipped_name, no_ref_or_error, invalid_ref, conflict_max, copy_error, extraction_error
    """
    nom_fichier_original = os.path.basename(pdf_path)
    nouveau_nom = None
    donnees_extraites = None
    status = "unknown_error" # Default status

    # 1. Vérifier si le fichier doit être traité (basé sur le nom)
    # Adaptez cette condition si nécessaire (ex: ou si un flag force le traitement)
    # if "REFERENCE" not in nom_fichier_original.upper():
    #     return "skipped_name", nom_fichier_original, None, None
    # Simplification : on essaie de traiter tous les PDF trouvés, le filtrage se fera sur l'extraction

    # 2. Extraire les données d'abord (la référence est dedans)
    donnees_extraites = extraire_donnees_pdf(pdf_path)

    if donnees_extraites is None:
        # Erreur critique pendant l'extraction (déjà logguée dans la fonction)
        return "extraction_error", nom_fichier_original, None, None

    ref = donnees_extraites.get("Reference Rapport", "")

    # 3. Vérifier si la référence est valide pour le renommage
    if not ref:
        # Pas de référence trouvée OU vide, on ne peut pas renommer correctement
        # On garde les données extraites si elles existent, mais on signale l'échec du renommage
        st.warning(f"⚠️ Référence vide ou non trouvée pour '{nom_fichier_original}', renommage impossible.")
        return "no_ref_found", nom_fichier_original, None, donnees_extraites # Nouveau status

    ref_clean = "".join(c for c in ref if c.isalnum() or c in ('-', '_', '.')).strip()
    if not ref_clean:
         # La référence extraite ne contient aucun caractère valide après nettoyage
         st.warning(f"⚠️ Référence '{ref}' invalide après nettoyage pour '{nom_fichier_original}', renommage impossible.")
         return "invalid_ref", nom_fichier_original, None, donnees_extraites # Statut existant

    # 4. Générer le nouveau nom et gérer les conflits
    nouveau_nom = f"RAPPORT - {ref_clean}.pdf"
    nouveau_chemin = os.path.join(dossier_sortie, nouveau_nom)

    count = 1
    base_name = f"RAPPORT - {ref_clean}"
    while os.path.exists(nouveau_chemin):
        nouveau_nom = f"{base_name}_{count}.pdf"
        nouveau_chemin = os.path.join(dossier_sortie, nouveau_nom)
        count += 1
        if count > 20:
             st.error(f"❌ Trop de conflits de nom pour '{ref_clean}' ({nom_fichier_original}).")
             # On a les données, mais le renommage/copie échoue ici
             return "conflict_max", nom_fichier_original, None, donnees_extraites # Statut existant

    # 5. Copier le fichier avec le nouveau nom
    try:
        shutil.copy2(pdf_path, nouveau_chemin)
        # Ajouter les noms de fichier aux données pour l'Excel
        donnees_extraites["Nom Fichier Original"] = nom_fichier_original
        donnees_extraites["Nouveau Nom Fichier"] = nouveau_nom
        return "success", nom_fichier_original, nouveau_nom, donnees_extraites # Succès complet
    except Exception as e:
        st.error(f"❌ Erreur copie '{nom_fichier_original}' → '{nouveau_nom}': {e}")
         # On a les données, mais la copie a échoué
        return "copy_error", nom_fichier_original, nouveau_nom, donnees_extraites # Statut existant


def creer_zip_avec_resultats(dossier_source, nom_zip_final, chemin_excel=None):
    """Crée une archive ZIP à partir du contenu (PDFs + Excel) du dossier source."""
    fichiers_ajoutes = 0
    try:
        with zipfile.ZipFile(nom_zip_final, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Ajouter les PDF renommés
            for root, _, files in os.walk(dossier_source):
                for file in files:
                    # Inclure uniquement les PDF (renommés)
                    if file.lower().endswith(".pdf"):
                        chemin_complet = os.path.join(root, file)
                        # Ajouter à la racine du ZIP
                        zipf.write(chemin_complet, arcname=file)
                        fichiers_ajoutes += 1

            # Ajouter le fichier Excel s'il existe
            if chemin_excel and os.path.exists(chemin_excel):
                zipf.write(chemin_excel, arcname=os.path.basename(chemin_excel))
                # On ne compte pas l'excel dans le compte principal pour l'instant
                # fichiers_ajoutes += 1

            if fichiers_ajoutes == 0 and (not chemin_excel or not os.path.exists(chemin_excel)):
                if os.path.exists(nom_zip_final): os.remove(nom_zip_final)
                return None, 0 # Aucun fichier à zipper

        # Retourner le chemin du zip et le nombre de PDF ajoutés
        return nom_zip_final, fichiers_ajoutes
    except Exception as e:
        st.error(f"❌ Erreur critique lors de la création de l'archive ZIP : {e}")
        if os.path.exists(nom_zip_final):
            try: os.remove(nom_zip_final)
            except OSError: pass
        return None, 0


# --- Interface Principale Streamlit ---

# Initialisation Session State
if 'zip_path' not in st.session_state: st.session_state['zip_path'] = None
if 'excel_path' not in st.session_state: st.session_state['excel_path'] = None # Ajout
if 'processing_done' not in st.session_state: st.session_state['processing_done'] = False
if 'summary_stats' not in st.session_state: st.session_state['summary_stats'] = {}
if 'all_extracted_data' not in st.session_state: st.session_state['all_extracted_data'] = [] # Stocker les données extraites

# --- Section 1: Dépôt des Fichiers ---
st.subheader("1. Déposer les fichiers")
uploaded_files = st.file_uploader(
    "Sélectionnez des PDF ou une archive ZIP",
    accept_multiple_files=True,
    type=['zip', 'pdf'],
    help="Déposez des PDF ou une archive ZIP contenant vos rapports.",
    label_visibility="collapsed"
)

st.divider()

# --- Section 2: Lancement du Traitement ---
st.subheader("2. Lancer le traitement")
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    lancer_traitement = st.button(
        "🚀 Lancer le Traitement", # Nom bouton mis à jour
        disabled=(not uploaded_files),
        use_container_width=True,
        type="primary"
    )

st.divider()

# --- Section 3: Traitement (si bouton cliqué) ---
if lancer_traitement:
    # Réinitialisation
    st.session_state['zip_path'] = None
    st.session_state['excel_path'] = None
    st.session_state['processing_done'] = False
    st.session_state['summary_stats'] = {}
    st.session_state['all_extracted_data'] = [] # Vider les données précédentes

    files_found_count = 0
    files_processed_count = 0 # Compte les fichiers où le traitement a été tenté
    files_succeeded_rename_count = 0 # Compte les renommages/copies réussis
    files_succeeded_extraction_count = 0 # Compte les extractions réussies (même si renommage échoue)
    files_failed_count = 0 # Compte les échecs globaux (extraction ou copie)
    failed_files_details = []
    all_pdf_paths_to_process = []
    extracted_data_list = [] # Liste pour stocker les dictionnaires de données

    if uploaded_files:
        with tempfile.TemporaryDirectory() as temp_input_dir, \
             tempfile.TemporaryDirectory() as temp_output_dir: # Sortie pour PDFs renommés et Excel

            prep_placeholder = st.info("📁 Préparation des fichiers...")
            # ... (Code de préparation/extraction ZIP identique à avant) ...
            with st.spinner("Analyse des fichiers uploadés..."):
                zip_extracted_count = 0
                pdf_saved_count = 0
                for uploaded_file in uploaded_files:
                    temp_file_path = os.path.join(temp_input_dir, uploaded_file.name)
                    try:
                        with open(temp_file_path, "wb") as f: f.write(uploaded_file.getbuffer())
                    except Exception as e:
                        st.error(f"❌ Erreur sauvegarde '{uploaded_file.name}': {e}")
                        continue

                    if uploaded_file.type == "application/zip" or temp_file_path.lower().endswith(".zip"):
                        try:
                            with zipfile.ZipFile(temp_file_path, 'r') as zip_ref:
                                zip_ref.extractall(temp_input_dir)
                            zip_extracted_count +=1
                            # Ne pas supprimer le zip tout de suite si on veut le réutiliser
                            # os.remove(temp_file_path)
                        except Exception as e:
                             st.error(f"❌ Erreur extraction '{uploaded_file.name}' : {e}")
                             # try: os.remove(temp_file_path) except OSError: pass # Ne pas supprimer en cas d'erreur
                    else:
                        pdf_saved_count += 1

            prep_placeholder.info(f"📁 Préparation terminée. {pdf_saved_count} PDF direct(s), {zip_extracted_count} ZIP(s) trouvé(s).")


            for root, dirs, files in os.walk(temp_input_dir):
                 # Exclure les dossiers cachés et spécifiques à MacOSX
                 dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__MACOSX']
                 for file in files:
                    if file.lower().endswith(".pdf") and not file.startswith('._'): # Exclure les fichiers macOS temporaires
                        all_pdf_paths_to_process.append(os.path.join(root, file))
            files_found_count = len(all_pdf_paths_to_process)

            if files_found_count == 0:
                 st.warning("⚠️ Aucun fichier PDF trouvé à traiter.")
            else:
                st.info(f"⚙️ Traitement de {files_found_count} fichier(s) PDF...")
                progress_placeholder = st.empty()
                progress_bar = progress_placeholder.progress(0, text="Analyse en cours...")

                for i, pdf_path in enumerate(all_pdf_paths_to_process):
                    files_processed_count += 1 # Compte chaque tentative
                    status, original_name, new_name, extracted_data = traiter_pdf_et_extraire(pdf_path, temp_output_dir)

                    # Mise à jour compteurs et détails d'échec
                    if status == "success":
                        files_succeeded_rename_count += 1
                        files_succeeded_extraction_count += 1 # Succès implique extraction réussie
                        if extracted_data: # S'assurer que les données existent
                             extracted_data_list.append(extracted_data)
                    elif status in ["no_ref_found", "invalid_ref", "conflict_max", "copy_error"]:
                        # Renommage/Copie a échoué, mais l'extraction a pu réussir
                        files_failed_count += 1
                        reason = status.replace("_", " ").capitalize()
                        failed_files_details.append({"file": original_name, "reason": f"Échec renommage/copie ({reason})"})
                        if extracted_data:
                            # On a quand même les données, on les ajoute pour l'Excel
                            files_succeeded_extraction_count += 1
                            extracted_data["Nom Fichier Original"] = original_name
                            extracted_data["Nouveau Nom Fichier"] = "ERREUR_RENOMMAGE" # Marqueur dans l'excel
                            extracted_data_list.append(extracted_data)
                    elif status == "extraction_error":
                        files_failed_count += 1
                        failed_files_details.append({"file": original_name, "reason": "Erreur extraction données"})
                    elif status == "skipped_name":
                         files_processed_count -= 1 # Ne pas compter comme traité si skippé par nom
                         pass # Ignoré, pas un échec direct
                    else: # unknown_error ou autre
                        files_failed_count += 1
                        failed_files_details.append({"file": original_name, "reason": "Erreur inconnue"})


                    # Mise à jour de la barre de progression
                    progress_text = f"Traitement PDF {i+1}/{files_found_count}"
                    progress_bar.progress((i + 1) / files_found_count, text=progress_text)

                progress_placeholder.empty() # Nettoyer la barre

                st.session_state['all_extracted_data'] = extracted_data_list # Sauvegarder les données

                # --- Génération Excel ---
                final_excel_path = None
                if extracted_data_list: # S'il y a des données à mettre dans l'Excel
                    st.info("📊 Génération du fichier Excel récapitulatif...")
                    try:
                        # Définir l'ordre souhaité des colonnes
                        colonnes_ordre = [
                            "Nom Fichier Original", "Nouveau Nom Fichier", "Reference Rapport", "FOS",
                            "Adresse Travaux", "Nom Beneficiaire", "Raison Sociale Professionnel",
                            "Beneficiaire Joint", "Telephone Errone", "Controle Realise", "Date Controle",
                            "Systeme Regulation Installe", "Reception Consignes Emetteurs",
                            "Commentaire Non Reception", "Absence Non Qualite Manifeste",
                            "Commentaire Non Qualite Relevee", "Conclusion Controle"
                        ]
                        df = pd.DataFrame(extracted_data_list)
                        # Réorganiser les colonnes et ajouter celles manquantes si nécessaire
                        df = df.reindex(columns=colonnes_ordre, fill_value="")

                        excel_filename = "recapitulatif_controles_greenprime.xlsx"
                        final_excel_path = os.path.join(temp_output_dir, excel_filename)

                        # Utiliser openpyxl comme moteur pour une meilleure compatibilité
                        df.to_excel(final_excel_path, index=False, engine='openpyxl')
                        st.session_state['excel_path'] = final_excel_path
                        st.success(f"✅ Fichier Excel '{excel_filename}' généré.")
                    except Exception as e:
                        st.error(f"❌ Erreur lors de la génération du fichier Excel : {e}")
                        st.session_state['excel_path'] = None
                else:
                    st.warning("⚠️ Aucune donnée extraite avec succès pour générer le fichier Excel.")


                # --- Création ZIP (Maintenant avec l'Excel) ---
                if files_succeeded_rename_count > 0 or st.session_state['excel_path']:
                    st.info("📦 Création de l'archive ZIP...")
                    # Créer un chemin temporaire pour le zip final en dehors du dossier temp_output_dir
                    fd, final_zip_path_temp = tempfile.mkstemp(suffix=".zip", prefix="resultats_greenprime_")
                    os.close(fd)

                    zip_path, zip_pdf_count = creer_zip_avec_resultats(temp_output_dir, final_zip_path_temp, st.session_state['excel_path'])
                    st.session_state['zip_path'] = zip_path
                    if zip_path:
                        msg = f"✅ Archive ZIP créée avec {zip_pdf_count} PDF(s)"
                        if st.session_state['excel_path']: msg += " et le fichier Excel."
                        else: msg += "."
                        st.success(msg)
                    else:
                         st.error("❌ Échec critique lors de la création de l'archive ZIP finale.")
                else:
                    st.warning("Aucun PDF renommé avec succès et pas de fichier Excel à inclure. Archive ZIP non créée.")


            st.session_state['processing_done'] = True
            # Stockage des stats pour affichage
            st.session_state['summary_stats'] = {
                "found": files_found_count,
                "processed": files_processed_count,
                "succeeded_rename": files_succeeded_rename_count,
                "succeeded_extraction": files_succeeded_extraction_count,
                "failed": files_failed_count,
                "failures": failed_files_details
            }

    else: # Cas "not uploaded_files" déjà géré par disabled button
        st.warning("Veuillez déposer au moins un fichier ZIP ou PDF.")


# --- Section 4: Affichage du Résumé et Téléchargement ---
if st.session_state['processing_done']:

    stats = st.session_state.get('summary_stats', {})
    if not stats and not uploaded_files:
         pass # Ne rien afficher
    elif not stats and uploaded_files:
         st.warning("Aucune donnée à résumer (aucun PDF trouvé ou traité).")
    elif stats:
        st.subheader("📊 Résumé du Traitement")
        col1, col2, col3 = st.columns(3) # Trois colonnes pour mieux répartir
        with col1:
            st.metric(label="PDF Trouvés", value=f"{stats.get('found', 0)}")
            st.metric(label="PDF Traités", value=f"{stats.get('processed', 0)}")
        with col2:
            st.metric(label="✅ Renommages Réussis", value=f"{stats.get('succeeded_rename', 0)}")
            st.metric(label="📊 Extractions Réussies", value=f"{stats.get('succeeded_extraction', 0)}")
        with col3:
             st.metric(label="❌ Échecs (Total)", value=f"{stats.get('failed', 0)}")
             # Afficher les détails des échecs s'il y en a
             failed_count = stats.get('failed', 0)
             if failed_count > 0:
                 with st.expander(f"🔍 Voir détails des {failed_count} échec(s)"):
                     df_failures = pd.DataFrame(stats.get('failures', []))
                     if not df_failures.empty:
                         df_failures.columns = ["Fichier", "Raison de l'échec"]
                         st.table(df_failures)
                     else:
                         st.write("Aucun détail d'échec spécifique enregistré.")


    # --- Section Téléchargement ---
    zip_path_final = st.session_state.get('zip_path')
    excel_path_final = st.session_state.get('excel_path')

    if zip_path_final and os.path.exists(zip_path_final):
        st.divider()
        st.subheader("3. Télécharger les résultats")
        col_dl1, col_dl2 = st.columns(2) # Deux colonnes pour les boutons

        with col_dl1:
             with open(zip_path_final, "rb") as fp_zip:
                st.download_button(
                    label="📥 Télécharger l'Archive ZIP (PDFs + Excel)",
                    data=fp_zip,
                    file_name="rapports_greenprime_traites.zip", # Nom de fichier personnalisé
                    mime="application/zip",
                    use_container_width=True,
                    type="primary"
                )

        # Optionnel: Bouton séparé pour l'Excel si généré
        if excel_path_final and os.path.exists(excel_path_final):
             with col_dl2:
                  with open(excel_path_final, "rb") as fp_excel:
                     st.download_button(
                         label="📊 Télécharger Fichier Excel seul",
                         data=fp_excel,
                         file_name="recapitulatif_controles_greenprime.xlsx",
                         mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         use_container_width=True
                     )
        elif st.session_state.get('all_extracted_data'): # Si on a extrait des données mais l'excel a échoué
             with col_dl2:
                 st.warning("Le fichier Excel n'a pas pu être généré ou inclus dans le ZIP.")


    elif st.session_state['processing_done']:
        # Afficher un message si le traitement est fini mais rien à télécharger
        st.info("ℹ️ Aucun fichier n'a été traité avec succès ou aucune donnée n'a été extraite. Aucun fichier à télécharger.")

    # Nettoyage potentiel des fichiers temporaires du state (si nécessaire)
    # Normalement, les TemporaryDirectory s'en chargent, mais si on stocke des chemins
    # comme zip_path en dehors, il faudrait les supprimer explicitement après usage
    # (peut-être à la fin de la session ou au prochain lancement)pip