# Graphique

## Description
Application Streamlit produisant un conseil financier à partir de données Google Sheets. Elle effectue une analyse technique (RSI, moyennes mobiles, bandes de Bollinger, rendements) et affiche une recommandation textuelle.

## Prérequis logiciels
- Python 3.9 ou version ultérieure
- Dépendances Python listées dans `requirements_mcp_http.txt`

## Installation
1. Cloner le dépôt :
   ```bash
   git clone <URL-du-depot>
   cd Graphique-
   ```
2. Installer les dépendances :
   ```bash
   pip install -r requirements_mcp_http.txt
   ```

## Lancement de l'application
Exécuter la commande suivante :
```bash
streamlit run app_mcp_http.py
```

## Fichiers principaux
- `app_mcp_http.py` : script Streamlit principal.
- `requirements_mcp_http.txt` : liste des dépendances requises.

## Exemple de flux de travail
1. Cloner le dépôt et installer les dépendances.
2. Lancer l'application avec `streamlit run app_mcp_http.py`.
3. Ouvrir l'URL fournie par Streamlit dans un navigateur pour obtenir le conseil financier.
