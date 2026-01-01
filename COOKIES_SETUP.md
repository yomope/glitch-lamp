# Résolution du problème de blocage YouTube ("Sign in to confirm you’re not a bot")

Depuis fin 2024, YouTube a considérablement renforcé ses protections contre les outils de téléchargement automatisés comme `yt-dlp`, bloquant souvent les requêtes provenant de serveurs avec l'erreur :
`Sign in to confirm you’re not a bot`

La solution la plus fiable est d'utiliser les cookies de votre propre navigateur pour authentifier les requêtes du backend.

## Procédure pas à pas

### 1. Installer une extension d'export de cookies
Sur votre navigateur habituel (Chrome, Firefox, Edge), installez une extension capable d'exporter les cookies au format Netscape (compatible `wget`/`curl`).

*   **Chrome / Brave / Edge** : [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflccgomilekfcg)
*   **Firefox** : [cookies.txt](https://addons.mozilla.org/fr/firefox/addon/cookies-txt/)

### 2. Se connecter à YouTube
1.  Allez sur [youtube.com](https://www.youtube.com).
2.  Assurez-vous d'être connecté à votre compte Google (même un compte gratuit fonctionne).
3.  Naviguez sur une vidéo au hasard pour vérifier que tout fonctionne.

### 3. Exporter le fichier `cookies.txt`
1.  Cliquez sur l'icône de l'extension que vous venez d'installer.
2.  Assurez-vous que l'onglet actif est bien YouTube.
3.  Cliquez sur le bouton **"Export"** ou **"Download"**.
4.  Enregistrez le fichier sous le nom exact : `cookies.txt`.

### 4. Installer le fichier sur le serveur
Déposez ce fichier `cookies.txt` à la racine du dossier du projet Glitch Lamp :

```bash
/home/yomope/glitch-lamp/cookies.txt
```

*(Si vous ne pouvez pas le mettre à la racine, le backend le cherchera aussi dans le dossier `backend/`).*

### 5. Redémarrer le backend
Une fois le fichier en place, redémarrez le service backend pour qu'il prenne en compte les nouveaux cookies.

Le backend affichera dans les logs :
`INFO - Using cookies from /home/yomope/glitch-lamp/cookies.txt`

---

**Note** : Les cookies expirent après un certain temps (quelques mois). Si l'erreur recommence, il faudra refaire cette procédure pour générer un fichier `cookies.txt` à jour.
