# Instructions pour publier sur GitHub

Le dépôt Git local a été créé avec succès. Pour publier sur GitHub, suivez ces étapes :

## 1. Créer un dépôt sur GitHub

1. Allez sur [GitHub.com](https://github.com) et connectez-vous
2. Cliquez sur le bouton "+" en haut à droite, puis "New repository"
3. Donnez un nom à votre dépôt (par exemple : `glitch-lamp`)
4. **Ne cochez PAS** "Initialize this repository with a README" (on a déjà un README)
5. Cliquez sur "Create repository"

## 2. Ajouter le remote GitHub et pousser

Une fois le dépôt créé sur GitHub, exécutez ces commandes (remplacez `VOTRE_USERNAME` et `NOM_DU_REPO` par vos valeurs) :

```bash
cd /home/yomope/glitch_lamp

# Ajouter le remote GitHub
git remote add origin https://github.com/VOTRE_USERNAME/NOM_DU_REPO.git

# Renommer la branche en 'main' (si GitHub utilise 'main' par défaut)
git branch -M main

# Pousser le code sur GitHub
git push -u origin main
```

## Alternative : Utiliser SSH

Si vous avez configuré une clé SSH sur GitHub :

```bash
git remote add origin git@github.com:VOTRE_USERNAME/NOM_DU_REPO.git
git branch -M main
git push -u origin main
```

## 3. Vérification

Après avoir poussé, vous devriez voir tous vos fichiers sur GitHub à l'adresse :
`https://github.com/VOTRE_USERNAME/NOM_DU_REPO`

## Notes

- Les fichiers suivants sont exclus du dépôt (via .gitignore) :
  - `temp_videos/` - Vidéos temporaires générées
  - `uploads/` - Fichiers uploadés par les utilisateurs
  - `exports/` - Vidéos exportées
  - `logs/` - Fichiers de log
  - `__pycache__/` - Cache Python
  - `*.pyc` - Fichiers compilés Python
  - `venv/` - Environnement virtuel Python
  - `*.exe` - Exécutables Windows

- Les fichiers suivants sont inclus :
  - Tout le code source (frontend, backend)
  - Les scripts d'installation
  - README.md et PLAN.md
  - requirements.txt
  - .gitignore
