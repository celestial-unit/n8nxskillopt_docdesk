# Requirements Document

## Introduction

Ce document décrit les exigences fonctionnelles et non-fonctionnelles d'un pipeline multi-agents de traitement de documents comptables (factures, reçus, bons de commande) pour des entreprises tunisiennes fictives. Le système utilise n8n comme orchestrateur de workflow, FastAPI comme backend, des agents LLM spécialisés, une couche RAG (Retrieval-Augmented Generation), et un tableau de bord React. Chaque document traverse les étapes : routage → extraction → codification (avec RAG) → validation → escalade humaine si nécessaire. L'objectif est un démonstrateur fonctionnel produisant des résultats chiffrés issus d'exécutions réelles.

---

## Glossary

- **Pipeline**: L'ensemble du système de traitement de documents de l'entrée à la décision finale.
- **Agent**: Un composant qui effectue exactement un appel LLM pour accomplir un rôle spécifique.
- **Router**: L'agent qui détermine le type de document et la modalité (texte ou photo).
- **Extractor**: L'agent qui extrait les champs structurés d'un document.
- **Coder**: L'agent qui attribue un code comptable via RAG et cite la règle utilisée.
- **Validator**: L'agent qui combine des vérifications Python déterministes avec une explication LLM d'une phrase.
- **Exception_Handler**: L'agent qui prépare le dossier d'escalade vers un humain.
- **Skill**: Un fichier Markdown `skills/<company>/<agent>/v<NNN>.md` servant de prompt système pour un agent.
- **Trace**: L'enregistrement complet d'un appel d'agent (étape, statut, durée ms, sortie, chunks récupérés avec scores, version du skill) dans SQLite.
- **Gold JSON**: Le label de référence d'un document synthétique (doc_type, fields, account_code, injected_errors).
- **LLM_Client**: Le module d'accès unifié aux modèles de langage (Azure AI Foundry ou endpoint OpenAI-compatible).
- **RAG_Engine**: Le module de récupération vectorielle basé sur Qdrant embarqué.
- **Qdrant_Local**: Instance Qdrant embarquée initialisée via `QdrantClient(path="./qdrant_local")`.
- **Company_A**: Entreprise fictive tunisienne, monnaie TND, TVA 19%, codes à 6 caractères.
- **Company_B**: Entreprise fictive tunisienne, monnaies EUR/TND, TVA 7/13/19%, codes de type `6010-CC001`.
- **SCE**: Système Comptable des Entreprises tunisien, structurant les comptes de classe 6.
- **HTVA**: Hors Taxe sur la Valeur Ajoutée.
- **TTC**: Toutes Taxes Comprises.
- **Timbre_Fiscal**: Ligne obligatoire sur les documents commerciaux tunisiens représentant un droit de timbre.
- **NIF**: Numéro d'Identification Fiscale tunisien.
- **DEMO_CACHE**: Variable d'environnement activant le cache disque des réponses LLM par hash de prompt.
- **Selection_Set**: Ensemble de 20% des données utilisé pour l'optimisation de prompts (jamais le TEST).
- **Test_Set**: Ensemble de 30% des données, lu uniquement lors de la comparaison finale.
- **n8n_Workflow**: Le workflow JSON importable dans n8n décrivant l'orchestration des agents.
- **Inbox**: Répertoire `./inbox` où transitent les fichiers en cours de traitement.

---

## Requirements

---

### Requirement 1: Client LLM unifié

**User Story:** En tant que développeur, je veux un client LLM unique qui supporte Azure AI Foundry et les endpoints OpenAI-compatibles, afin de ne pas modifier le code des agents lors d'un changement de fournisseur.

#### Acceptance Criteria

1. THE LLM_Client SHALL lire depuis le fichier `.env` les variables `AZURE_ENDPOINT`, `AZURE_API_KEY`, un nom de déploiement par rôle (`AGENT_DEPLOYMENT`, `VISION_DEPLOYMENT`, `OPTIMIZER_DEPLOYMENT`), et optionnellement `AZURE_API_VERSION`.
2. THE LLM_Client SHALL aussi accepter un endpoint OpenAI-compatible via la variable `OPENAI_BASE_URL` et `OPENAI_API_KEY`, sans modifier le code appelant.
3. THE LLM_Client SHALL fixer la température à 0 pour tous les appels, sans exception.
4. WHEN `DEMO_CACHE=1` est défini dans l'environnement, THE LLM_Client SHALL mettre en cache sur disque la réponse de chaque appel LLM en utilisant le hash SHA-256 du prompt comme clé, et retourner la réponse en cache lors d'appels identiques ultérieurs.
5. IF la variable d'environnement du déploiement correspondant au rôle demandé est absente, THEN THE LLM_Client SHALL lever une exception explicite nommant la variable manquante.
6. WHEN `DEMO_CACHE=1` est actif et qu'une entrée de cache est trouvée, THE LLM_Client SHALL retourner la réponse en cache sans effectuer d'appel réseau.

---

### Requirement 2: Générateur de données synthétiques

**User Story:** En tant que chercheur, je veux un générateur de données déterministe (seed 42) produisant des documents réalistes pour deux entreprises tunisiennes fictives, afin d'avoir un corpus d'entraînement et d'évaluation reproductible.

#### Acceptance Criteria

1. THE Data_Generator SHALL initialiser son générateur de nombres aléatoires avec la graine 42, rendant chaque exécution identique.
2. THE Data_Generator SHALL créer pour Company_A : un plan de comptes d'au moins 20 lignes modélisé sur la classe 6 du SCE tunisien, une liste d'au moins 10 fournisseurs (incluant STEG, SONEDE, Tunisie Telecom, Ooredoo, Orange, Monoprix, Carrefour, stations-service et fournisseurs IT avec faux numéros et NIF), des règles de codification en Markdown, et 4 règles maison cachées apparaissant uniquement dans les gold labels.
3. THE Data_Generator SHALL créer pour Company_B : un plan de comptes d'au moins 20 lignes, une liste d'au moins 10 fournisseurs, des règles de codification en Markdown, et 4 règles maison cachées distinctes de celles de Company_A.
4. THE Data_Generator SHALL générer environ 30 documents par entreprise (factures, reçus, bons de commande) comme PDFs avec couche texte (reportlab), accompagnés chacun d'un gold JSON contenant `doc_type`, `fields`, `account_code`, et `injected_errors`.
5. WHEN un document est sélectionné pour injection d'erreur (30% des documents), THE Data_Generator SHALL injecter exactement un des types d'erreurs suivants : identifiant dupliqué, incohérence arithmétique, ou numéro d'identification fiscale manquant.
6. THE Data_Generator SHALL produire pour chaque PDF une variante photo en rendant le PDF en image avec Pillow, en appliquant une légère rotation et du bruit.
7. THE Data_Generator SHALL répartir les documents en TRAIN (50%), SELECTION (20%), TEST (30%) de manière déterministe avec seed 42.
8. THE Data_Generator SHALL ne jamais charger ni exposer le TEST set hors du module de comparaison finale.
9. THE Data_Generator SHALL créer un dossier `demo/` contenant exactement 4 documents : un PDF propre, un photo désordonnée, un document avec règle maison, et un document avec erreur arithmétique.
10. THE Data_Generator SHALL produire tous les documents en français.
11. THE Data_Generator SHALL formater les montants en TND avec 3 décimales et le format français (ex : `1 011,500`).
12. THE Data_Generator SHALL utiliser le format de date `jj/mm/aaaa`.
13. THE Data_Generator SHALL inclure dans chaque document les lignes HTVA, TVA, TTC, et une ligne Timbre_Fiscal.
14. THE Data_Generator SHALL inclure un champ NIF (Numéro d'Identification Fiscale) de style tunisien sur chaque document fournisseur.
15. THE Data_Generator SHALL appliquer le taux de TVA de 19% pour Company_A, et les taux 7%, 13%, ou 19% selon la ligne de produit pour Company_B.
16. THE Data_Generator SHALL utiliser des codes de compte à 6 caractères pour Company_A et des codes de format `6010-CC001` pour Company_B.

---

### Requirement 3: Dossier de données réelles annotées

**User Story:** En tant qu'évaluateur, je veux un dossier `real/` pour des documents photographiés réels que j'annoterai manuellement, afin de mesurer les performances sur des données du monde réel séparément des données synthétiques.

#### Acceptance Criteria

1. THE Pipeline SHALL créer et documenter la structure du dossier `real/` acceptant 15 à 20 documents photographiés réels avec leurs labels JSON manuels suivant le même schéma que les gold labels synthétiques.
2. THE Pipeline SHALL reporter les résultats sur le real set séparément des résultats synthétiques dans tous les rapports d'évaluation.
3. THE Pipeline SHALL ne jamais utiliser les données du dossier `real/` pour l'optimisation de prompts ou l'entraînement.
4. IF un fichier dans `real/` ne possède pas de label JSON associé, THEN THE Pipeline SHALL l'ignorer dans les calculs de scores et l'indiquer dans le rapport.

---

### Requirement 4: Agents du pipeline

**User Story:** En tant qu'architecte système, je veux cinq agents spécialisés effectuant chacun exactement un appel LLM, pilotés par des fichiers skill versionnés, afin de garantir la traçabilité et la reproductibilité de chaque décision.

#### Acceptance Criteria

1. THE Router SHALL déterminer le type de document (`invoice`, `receipt`, `purchase_order`) et la modalité (`text` ou `photo`) en un seul appel LLM, et retourner ces deux champs dans sa réponse.
2. THE Extractor SHALL extraire l'ensemble des champs structurés d'un document (fournisseur, date, numéro, lignes, montants HTVA/TVA/TTC, Timbre_Fiscal, NIF) en un seul appel LLM.
3. THE Coder SHALL attribuer un code comptable en effectuant une recherche RAG, et SHALL citer explicitement dans sa réponse la règle récupérée justifiant le code choisi.
4. THE Validator SHALL effectuer d'abord des vérifications Python déterministes sur les champs extraits (cohérence arithmétique, présence du NIF, absence de doublon d'identifiant), puis SHALL générer une explication d'une seule phrase via un appel LLM.
5. THE Exception_Handler SHALL préparer un dossier d'escalade structuré en un seul appel LLM lorsque le Validator signale qu'une révision humaine est nécessaire.
6. THE Pipeline SHALL charger le skill de chaque agent depuis `skills/<company_id>/<agent_name>/v<NNN>.md` et SHALL utiliser ce fichier comme prompt système de l'appel LLM correspondant.
7. WHEN un skill de version supérieure existe pour un agent, THE Pipeline SHALL utiliser la version la plus récente sauf instruction contraire explicite.
8. THE Pipeline SHALL enregistrer la version du skill utilisée dans chaque trace.

---

### Requirement 5: Scorers d'évaluation

**User Story:** En tant qu'évaluateur, je veux des métriques précises et reproduites pour chaque agent, afin de quantifier les améliorations entre versions de prompts.

#### Acceptance Criteria

1. THE Extractor_Scorer SHALL calculer le normalized exact match entre les champs extraits et les gold labels en normalisant les espaces, la casse, et le format des nombres avant comparaison.
2. THE Coder_Scorer SHALL attribuer un score de 1.0 si et seulement si le code comptable correspond au gold label ET la règle citée par le Coder apparaît textuellement dans le fichier skill ou dans les chunks récupérés ; dans tous les autres cas, THE Coder_Scorer SHALL attribuer 0.0.
3. THE Validator_Scorer SHALL calculer un F1 pondéré où les faux négatifs (erreurs non détectées) coûtent deux fois plus que les faux positifs.
4. WHEN les listes de prédictions et de références sont toutes deux vides, THE Validator_Scorer SHALL retourner 1.0.
5. THE Scorer_Suite SHALL calculer tous les scores uniquement à partir d'exécutions réelles, sans valeurs simulées.

---

### Requirement 6: API FastAPI

**User Story:** En tant qu'intégrateur, je veux une API REST avec CORS activé exposant exactement les endpoints nécessaires, afin que n8n et l'interface utilisateur puissent orchestrer le pipeline.

#### Acceptance Criteria

1. THE FastAPI_Server SHALL exposer exactement les endpoints suivants et aucun autre : `POST /route`, `POST /extract`, `POST /code`, `POST /validate`, `POST /handle`, `POST /accept`, `POST /escalate`, `POST /fail`, `GET /trace/{id}`, `GET /health`.
2. THE FastAPI_Server SHALL activer CORS pour toutes les origines afin de permettre les appels depuis l'interface React et n8n.
3. WHEN un appel est reçu sur n'importe quel endpoint, THE FastAPI_Server SHALL écrire un événement de trace dans SQLite contenant : étape, statut, durée en millisecondes, sortie de l'agent, chunks récupérés avec leurs scores de similarité, et version du skill utilisé.
4. THE FastAPI_Server SHALL utiliser le répertoire `./inbox` pour le transit des fichiers en cours de traitement.
5. THE FastAPI_Server SHALL retourner un statut HTTP 200 avec `{"status": "ok"}` sur `GET /health` si tous les composants internes (Qdrant, SQLite, LLM_Client) sont accessibles.
6. IF un composant interne est inaccessible lors d'un appel à `GET /health`, THEN THE FastAPI_Server SHALL retourner HTTP 503 avec le nom du composant défaillant.
7. THE FastAPI_Server SHALL démarrer sans erreur via `python run.py`.

---

### Requirement 7: Workflow n8n

**User Story:** En tant qu'évaluateur de projet, je veux un workflow n8n importable et activable qui orchestre les cinq agents avec gestion des erreurs, afin de démontrer l'orchestration visuelle du pipeline.

#### Acceptance Criteria

1. THE n8n_Workflow SHALL être un fichier JSON valide importable via la commande `n8n import:workflow --input=<fichier>` sans erreur.
2. THE n8n_Workflow SHALL contenir exactement un nœud nommé pour chaque agent : `Router`, `Extractor`, `Coder`, `Validator`, `Exception_Handler`.
3. THE n8n_Workflow SHALL implémenter la séquence : Webhook → Router → Switch (modalité) → Extractor → Coder → Validator → IF needs_review → (Escalate | Accept) → Respond.
4. THE n8n_Workflow SHALL configurer chaque nœud agent avec 2 tentatives automatiques en cas d'échec.
5. THE n8n_Workflow SHALL inclure une branche `/fail` activée lorsque toutes les tentatives d'un nœud sont épuisées.
6. THE n8n_Workflow SHALL inclure des sticky notes décrivant l'architecture du pipeline sur le canvas.
7. WHEN le workflow est activé, THE n8n_Workflow SHALL traiter une requête `curl` de test envoyée au webhook sans erreur d'exécution.
8. THE Pipeline SHALL épingler une version compatible de n8n et la démarrer via `npx n8n` sans Docker.
9. THE n8n_Workflow SHALL être exporté après test et le JSON final doit être committé dans le dépôt.

---

### Requirement 8: Moteur RAG

**User Story:** En tant qu'agent Coder, je veux récupérer les règles comptables pertinentes depuis une base vectorielle filtrée par entreprise, afin de justifier chaque code attribué par une règle réelle.

#### Acceptance Criteria

1. THE RAG_Engine SHALL utiliser le modèle d'embeddings `paraphrase-multilingual-mpnet-base-v2` pour encoder les textes.
2. THE RAG_Engine SHALL implémenter deux stratégies de découpage : découpage fixe (512 tokens, overlap 64 tokens) et découpage sémantique par titres (maximum 1024 tokens par chunk).
3. THE RAG_Engine SHALL stocker les embeddings dans Qdrant_Local initialisé via `QdrantClient(path="./qdrant_local")`.
4. THE RAG_Engine SHALL filtrer les résultats de recherche par `company_id` pour garantir qu'une entreprise ne récupère jamais les règles d'une autre.
5. THE RAG_Engine SHALL être idempotent : ingérer les mêmes documents plusieurs fois ne doit pas créer de doublons.
6. THE RAG_Engine SHALL fournir 20 requêtes de test manuelles par entreprise (en français et en anglais) pour l'évaluation de la récupération.
7. THE RAG_Engine SHALL calculer Recall@5 et MRR@5 sur les requêtes de test et écrire les résultats avec un commentaire dans `eval/results/retrieval_eval.md`.
8. THE RAG_Engine SHALL enregistrer dans chaque trace les chunks récupérés avec leurs scores de similarité.
9. FOR ALL documents ingérés puis re-ingérés sans modification, THE RAG_Engine SHALL retourner les mêmes chunks et scores lors d'une recherche identique (propriété d'idempotence).

---

### Requirement 9: Multimodalité

**User Story:** En tant qu'utilisateur, je veux soumettre aussi bien des PDFs avec couche texte que des photos ou scans de documents, afin que le pipeline traite les deux formats sans configuration manuelle.

#### Acceptance Criteria

1. WHEN un fichier PDF avec couche texte est soumis, THE Pipeline SHALL extraire le texte via `pypdf` et l'envoyer au pipeline texte.
2. WHEN un fichier image (photo ou scan) est soumis, THE Pipeline SHALL envoyer l'image au déploiement `VISION_DEPLOYMENT` du LLM_Client pour obtenir une transcription texte, puis envoyer ce texte au pipeline standard.
3. THE Router SHALL détecter automatiquement la modalité du document soumis (`text` ou `photo`) et aiguiller vers la branche correspondante du workflow n8n.
4. THE Pipeline SHALL ne supporter aucune modalité audio ou vocale.

---

### Requirement 10: Évaluation de base (baseline)

**User Story:** En tant que chercheur, je veux des scores de base mesurés sur le SELECTION set pour les prompts v001, avec et sans RAG, afin d'avoir une référence avant toute optimisation.

#### Acceptance Criteria

1. THE Evaluation_Suite SHALL calculer et écrire dans `eval/results/baseline.md` les scores de chaque agent sur le SELECTION set en utilisant les skills v001.
2. THE Evaluation_Suite SHALL produire deux colonnes de scores pour le Coder : avec RAG activé et avec RAG désactivé.
3. THE Evaluation_Suite SHALL n'utiliser que des valeurs provenant d'exécutions réelles ; aucune valeur ne peut être estimée ou inventée.
4. WHEN des échecs réels sont collectés lors de l'évaluation baseline, THE Evaluation_Suite SHALL les enregistrer et les utiliser comme base pour les corrections manuelles de prompts.
5. THE Pipeline SHALL maintenir les versions v001 et v002 de chaque skill modifié, avec les scores associés documentés dans `eval/results/baseline.md`.

---

### Requirement 11: Bibliothèque de prompts

**User Story:** En tant qu'ingénieur prompts, je veux une bibliothèque documentant chaque prompt avec ses techniques, ses échecs observés et ses corrections, afin de constituer une référence méthodologique issue d'exécutions réelles.

#### Acceptance Criteria

1. THE Pipeline SHALL créer et maintenir `prompts/PROMPT_LIBRARY.md` contenant une entrée par prompt utilisé dans le système.
2. FOR EACH prompt entry, THE Pipeline SHALL documenter : le rôle de l'agent, la technique utilisée (few-shot, chain-of-thought, structured output, role prompting, guardrails), les échecs observés lors d'exécutions réelles, la correction apportée, et les scores avant/après.
3. THE Prompt_Library SHALL ne contenir que des observations issues d'exécutions réelles ; aucun échec hypothétique n'est acceptable.

---

### Requirement 12: Interface utilisateur (Tableau de bord Tactical)

**User Story:** En tant qu'opérateur, je veux un tableau de bord avec le style cyberpunk existant connecté aux données réelles du backend, afin de visualiser et piloter le pipeline en temps réel.

#### Acceptance Criteria

1. THE UI SHALL utiliser la base de code React + TypeScript + Tailwind existante dans `./ui` en conservant le style cyberpunk et la barre latérale.
2. THE UI SHALL remplacer toutes les données simulées par des appels réels à FastAPI et au webhook n8n.
3. THE Command_Center SHALL permettre de téléverser ou sélectionner un document, lancer le traitement, et afficher 5 cartes de progression (Router, Extractor, Coder, Validator, Decision) se mettant à jour par interrogation de `/trace` toutes les 500ms.
4. THE Command_Center SHALL afficher les KPIs agrégés et un badge `ACCEPTED` ou `ESCALATED` à la fin du traitement.
5. THE Agent_Network SHALL afficher les 5 agents avec leur statut en temps réel et la version du skill actuellement chargée.
6. THE Operations_View SHALL afficher la liste des documents traités et une vue de trace détaillée pour chaque document sélectionné.
7. THE Intelligence_View SHALL afficher les chunks récupérés avec des barres de similarité et le tableau de résultats de l'évaluation de récupération.
8. THE Systems_View SHALL afficher l'état de santé en temps réel de FastAPI, n8n, Qdrant_Local, et LLM_Client.
9. IF le dossier `./ui` est absent, THEN THE Pipeline SHALL fournir une page Streamlit de substitution affichant les mêmes cartes de progression que le Command_Center.

---

### Requirement 13: Point d'entrée unique (`run.py`)

**User Story:** En tant qu'évaluateur, je veux démarrer tout le système avec une seule commande, afin de simplifier la démonstration.

#### Acceptance Criteria

1. WHEN la commande `python run.py` est exécutée, THE Runner SHALL démarrer le serveur FastAPI, l'instance n8n via `npx n8n`, et le serveur de l'interface utilisateur.
2. THE Runner SHALL épingler une version de n8n compatible et la démarrer via `npx n8n` sans Docker.
3. IF un des composants ne démarre pas dans les 30 secondes, THEN THE Runner SHALL afficher un message d'erreur explicite nommant le composant défaillant et arrêter le démarrage.

---

### Requirement 14: Optimisation de skill (stretch goal)

**User Story:** En tant que chercheur, je veux utiliser SkillOpt pour optimiser automatiquement le skill de l'Extractor, afin de comparer les performances avant et après optimisation sur le TEST set.

#### Acceptance Criteria

1. WHERE SkillOpt est installé et fonctionnel, THE Optimizer SHALL lire sa documentation depuis `docs/skillopt_api.md` et exécuter exactement une optimisation sur le skill de l'Extractor en utilisant TRAIN pour les rollouts et SELECTION pour la validation.
2. WHERE SkillOpt est installé et fonctionnel, THE Optimizer SHALL comparer les scores v001 vs meilleure version sur le TEST set une seule fois.
3. IF SkillOpt échoue pour quelque raison que ce soit, THEN THE Optimizer SHALL s'arrêter immédiatement, afficher le message d'erreur reçu, et enregistrer l'échec dans `docs/failures.md`.
4. THE Optimizer SHALL n'utiliser que l'API réelle de SkillOpt ; aucune simulation ou contournement n'est acceptable.

---

### Requirement 15: Documentation

**User Story:** En tant qu'évaluateur de projet, je veux une documentation complète et précise décrivant l'architecture, le script de démonstration et les instructions d'installation, afin de comprendre et reproduire le système.

#### Acceptance Criteria

1. THE Documentation SHALL créer `docs/architecture.md` décrivant les rôles de chaque agent, les outils utilisés, le flux d'information entre composants, et une justification du choix de l'architecture multi-agents par rapport à un appel LLM monolithique ou d'autres architectures.
2. THE Documentation SHALL créer `DEMO.md` contenant un script de démonstration de 5 minutes couvrant les étapes clés du pipeline.
3. THE Documentation SHALL créer `README.md` contenant les instructions d'installation en moins de 10 lignes de commandes.
4. THE Documentation SHALL ne contenir aucun chiffre de performance inventé ; tous les résultats doivent provenir d'exécutions réelles.

---

### Requirement 16: Propriétés de correction du pipeline

**User Story:** En tant qu'ingénieur qualité, je veux des propriétés vérifiables par des tests automatisés sur les composants critiques, afin de détecter les régressions.

#### Acceptance Criteria

1. FOR ALL gold JSON documents, WHEN the Extractor processes a document with a text layer, THE Extractor SHALL return a JSON object whose keys are a superset of the keys present in the corresponding gold JSON `fields` dictionary.
2. FOR ALL valid account codes generated by the Coder for Company_A, THE Coder SHALL return a string matching the pattern `[A-Z0-9]{6}` (6 alphanumeric characters).
3. FOR ALL valid account codes generated by the Coder for Company_B, THE Coder SHALL return a string matching the pattern `[0-9]{4}-[A-Z]{2}[0-9]{3}` (format `6010-CC001`).
4. FOR ALL document batches ingested into the RAG_Engine, WHEN the same batch is ingested a second time, THE RAG_Engine SHALL return the same collection size as after the first ingestion (idempotence invariant).
5. FOR ALL trace events written to SQLite, THE Trace_Store SHALL contain non-null values for `step`, `status`, `duration_ms`, and `skill_version`.
6. WHEN the Validator receives an extracted document where the sum of HTVA amounts plus TVA amounts does not equal the TTC amount within a tolerance of 0.001 TND, THE Validator SHALL flag the document as requiring human review.
7. FOR ALL Validator calls where both the prediction list and the reference list are empty, THE Validator_Scorer SHALL return exactly 1.0.
8. FOR ALL LLM_Client calls made when `DEMO_CACHE=1` is active and a cache entry exists for the prompt hash, THE LLM_Client SHALL return the cached response and the total number of outbound network calls SHALL remain zero for that prompt.
9. FOR ALL data splits produced by the Data_Generator with seed 42, THE split proportions SHALL satisfy: TRAIN ≈ 50%, SELECTION ≈ 20%, TEST ≈ 30%, with each document appearing in exactly one split.
10. FOR ALL documents in the `demo/` folder processed through the full pipeline, THE Pipeline SHALL produce a final decision of either `ACCEPTED` or `ESCALATED` without raising an unhandled exception.
