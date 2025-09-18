# Quiz Extractor - Moodle PDF

**Quiz Extractor** est une application Python qui permet d'extraire automatiquement les questions de quiz depuis des fichiers PDF Moodle.  
Elle détecte les équations LaTeX et les met en forme pour un rendu lisible, et permet également d’afficher un aperçu du PDF avec navigation et zoom.

## Fonctionnalités

- Extraction avancée du texte et des annotations des fichiers PDF Moodle.
- Reconnaissance et encadrement automatique des équations LaTeX.
- Affichage du PDF dans l'application avec :
  - Zoom avant/arrière
  - Navigation entre les pages
  - Scroll vertical et horizontal
- Organisation des questions dans des onglets avec la possibilité de copier le contenu.
- Nettoyage automatique des éléments non pertinents (Moodle headers, notes internes, etc.)

## Installation

Cloner le dépôt :


git clone https://github.com/tonpseudo/quiz-extractor.git
cd quiz-extractor
Créer un environnement virtuel (recommandé) :

bash
Copier le code
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
Installer les dépendances :

bash
Copier le code
pip install -r requirements.txt
Usage
Lancer l'application :

bash
Copier le code
python main.py
Cliquez sur "Ouvrir un PDF" pour sélectionner un fichier Moodle.

Les questions extraites apparaîtront dans les onglets à gauche.

L’aperçu du PDF est visible à droite avec zoom et navigation.

Capture d'écran
<img width="1591" height="925" alt="image" src="https://github.com/user-attachments/assets/a3ea0be0-86d3-45a4-9e97-8ca02a5cfe41" />


Dépendances principales
customtkinter : interface moderne

PyPDF2 : extraction de métadonnées et annotations

pdfminer.six : extraction de texte

PyMuPDF (fitz) : rendu des pages PDF en images

Pillow : gestion des images

re et statistics : traitement du texte et analyse des positions
