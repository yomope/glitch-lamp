# Plan du Projet - Glitch Video Player

## 📋 Vue d'ensemble

**Glitch Video Player** est une application web qui génère et joue des clips vidéo glitchés de manière infinie à partir de YouTube, avec application d'effets visuels en temps réel.

---

## 🏗️ Architecture Actuelle

### Backend (FastAPI)
- **`main.py`** : Point d'entrée principal, API REST
- **`services/`** :
  - `youtube_service.py` : Gestion des téléchargements YouTube via yt-dlp
  - `effect_manager.py` : Orchestration des effets vidéo
- **`plugins/`** : Système modulaire d'effets vidéo
  - `base.py` : Classe abstraite `VideoEffect`
  - 15+ effets implémentés (glitch, datamosh, blur, tracking, etc.)

### Frontend (HTML/CSS/JS)
- **`index.html`** : Lecteur vidéo principal
- **`option.html`** : Panneau de configuration
- **`script.js`** : Logique de lecture et gestion des clips
- **`style.css`** : Styles visuels

### Configuration
- **`settings.json`** : Paramètres persistants
- **`presets/`** : Chaînes d'effets sauvegardées

---

## ✨ Fonctionnalités Existantes

### ✅ Implémentées
1. **Téléchargement YouTube**
   - Recherche par mots-clés
   - Support des playlists
   - Filtrage des vidéos (durée, reels)
   - Sélection aléatoire de clips

2. **Système d'effets**
   - Architecture modulaire (plugins)
   - Chaînes d'effets configurables
   - Options personnalisables par effet
   - Mode freestyle (chaînes aléatoires)
   - Mode preset aléatoire

3. **Interface utilisateur**
   - Lecteur vidéo en boucle infinie
   - Panneau de configuration (touche P)
   - Gestion des presets
   - Indicateur de chargement

4. **Configuration**
   - Durée et variation des clips
   - Mots-clés de recherche
   - URL de playlist
   - Effets actifs
   - Vitesse de lecture
   - Qualité vidéo

---

## 🎯 Améliorations Possibles

### Priorité Haute

#### 1. Gestion des erreurs et résilience
- [ ] Retry automatique en cas d'échec de téléchargement
- [ ] Gestion des timeouts plus robuste
- [ ] Fallback vers clips précédents si génération échoue
- [ ] Logging structuré (fichier + console)

#### 2. Performance et optimisation
- [ ] Cache des vidéos téléchargées (éviter re-téléchargement)
- [ ] Préchargement du clip suivant pendant la lecture
- [ ] Compression des vidéos traitées
- [ ] Nettoyage automatique du dossier `temp_videos`
- [ ] Traitement asynchrone des effets lourds

#### 3. Interface utilisateur
- [ ] Contrôles de lecture (play/pause, volume)
- [ ] Barre de progression
- [ ] Aperçu du clip suivant
- [ ] Statistiques (nombre de clips joués, temps total)
- [ ] Mode plein écran natif

### Priorité Moyenne

#### 4. Nouvelles fonctionnalités
- [ ] Support de plusieurs sources (Vimeo, fichiers locaux)
- [ ] Export de clips traités
- [ ] Historique des clips joués
- [ ] Partage de presets (import/export)
- [ ] Mode diaporama (images fixes avec effets)

#### 5. Qualité vidéo
- [ ] Détection automatique de la résolution optimale
- [ ] Support HDR
- [ ] Ajustement automatique de la qualité selon les performances

#### 6. Effets avancés
- [ ] Éditeur visuel de chaînes d'effets
- [ ] Prévisualisation en temps réel des effets
- [ ] Animations de paramètres d'effets
- [ ] Synchronisation audio-visuelle

### Priorité Basse

#### 7. Documentation
- [ ] Guide d'utilisation détaillé
- [ ] Documentation API
- [ ] Guide de développement de plugins
- [ ] Exemples de presets

#### 8. Tests
- [ ] Tests unitaires pour les services
- [ ] Tests d'intégration pour l'API
- [ ] Tests de performance

#### 9. Déploiement
- [ ] Configuration Docker
- [ ] Scripts de déploiement
- [ ] Variables d'environnement pour la configuration

---

## 📁 Structure du Code

```
glitch_lamp/
├── backend/
│   ├── main.py                 # API FastAPI principale
│   ├── services/               # Services métier
│   │   ├── youtube_service.py  # Téléchargement YouTube
│   │   └── effect_manager.py   # Gestion des effets
│   ├── plugins/                # Effets vidéo modulaires
│   │   ├── base.py            # Classe abstraite VideoEffect
│   │   ├── glitch.py          # Effet glitch
│   │   ├── datamosh.py        # Effet datamosh
│   │   └── ...                # Autres effets
│   └── presets/               # Presets sauvegardés
├── frontend/
│   ├── index.html             # Lecteur principal
│   ├── option.html            # Panneau de configuration
│   ├── script.js              # Logique frontend
│   └── style.css              # Styles
├── scripts/                   # Scripts d'installation/démarrage
└── temp_videos/              # Vidéos temporaires (généré)
```

---

## 🔧 Points Techniques Importants

### Flux de traitement
1. **Sélection vidéo** → Recherche YouTube ou playlist
2. **Téléchargement** → Clip de durée spécifiée via yt-dlp
3. **Traitement** → Application de la chaîne d'effets via FFmpeg/OpenCV
4. **Lecture** → Diffusion via FastAPI StaticFiles
5. **Boucle** → Répétition automatique

### Technologies clés
- **FastAPI** : Framework web asynchrone
- **yt-dlp** : Téléchargement YouTube
- **FFmpeg** : Traitement vidéo
- **OpenCV** : Traitement d'images
- **MediaPipe** : Tracking facial

### Points d'attention
- ⚠️ **Performance** : Traitement vidéo CPU-intensive
- ⚠️ **Stockage** : Accumulation de fichiers dans `temp_videos`
- ⚠️ **Réseau** : Dépendance à YouTube (rate limiting possible)
- ⚠️ **Compatibilité** : FFmpeg requis, dépendances système

---

## 🚀 Roadmap Suggérée

### Phase 1 : Stabilisation (1-2 semaines)
- Améliorer la gestion d'erreurs
- Implémenter le cache vidéo
- Nettoyage automatique des fichiers temporaires
- Logging structuré

### Phase 2 : Performance (2-3 semaines)
- Préchargement du clip suivant
- Optimisation du traitement vidéo
- Compression des sorties
- Détection automatique de qualité

### Phase 3 : Fonctionnalités (3-4 semaines)
- Contrôles de lecture avancés
- Export de clips
- Historique et statistiques
- Support multi-sources

### Phase 4 : Polish (2-3 semaines)
- Interface utilisateur améliorée
- Documentation complète
- Tests automatisés
- Configuration Docker

---

## 📝 Notes de Développement

### Ajouter un nouvel effet
1. Créer un fichier dans `backend/plugins/`
2. Hériter de `VideoEffect` (voir `base.py`)
3. Implémenter `process_frame()` ou `process_video()`
4. Définir `name`, `description`, `type`, `options`
5. L'effet sera automatiquement découvert au démarrage

### Modifier les paramètres par défaut
- Éditer `Settings` dans `main.py`
- Ou modifier `settings.json` directement

### Déboguer
- Vérifier les logs console du backend
- Vérifier la console navigateur (F12)
- Vérifier les fichiers dans `temp_videos/`

---

## 🎨 Idées Futures

- **Mode collaboratif** : Partage de clips en temps réel
- **IA** : Sélection intelligente de clips selon l'humeur
- **Audio** : Effets audio synchronisés avec les effets visuels
- **Mobile** : Application mobile native
- **Streaming** : Mode streaming continu sans découpage

---

*Dernière mise à jour : Généré automatiquement*
