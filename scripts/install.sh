#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SYSTEMD_DIR="$ROOT_DIR/scripts/systemd"
CURRENT_USER="$(id -un)"
CURRENT_GROUP="$(id -gn)"

cd "$ROOT_DIR"

write_backend_service() {
    mkdir -p "$SYSTEMD_DIR"
    cat > "$SYSTEMD_DIR/glitch-backend.service" <<EOF
[Unit]
Description=Glitch Lamp backend (uvicorn)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$ROOT_DIR
Environment=HOME=$HOME UVICORN_HOST=0.0.0.0 UVICORN_PORT=18000 PYTHONUNBUFFERED=1
ExecStart=$ROOT_DIR/venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 18000
User=$CURRENT_USER
Group=$CURRENT_GROUP
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
}

write_mpv_tty_service() {
    mkdir -p "$SYSTEMD_DIR"
    cat > "$SYSTEMD_DIR/glitch-mpv.service" <<EOF
[Unit]
Description=Glitch Lamp lecture mpv sur tty1
After=glitch-backend.service network-online.target systemd-user-sessions.service getty-pre.target plymouth-quit.service systemd-vconsole-setup.service
Wants=glitch-backend.service
Conflicts=getty@tty1.service

[Service]
Type=simple
WorkingDirectory=$ROOT_DIR
User=root
SupplementaryGroups=video render
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=no
StandardInput=tty-force
StandardOutput=journal+console
StandardError=journal+console
ExecStartPre=/usr/bin/chvt 1
ExecStart=$ROOT_DIR/scripts/run_mpv-2.sh
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
}

write_mpv_user_service() {
    mkdir -p "$SYSTEMD_DIR"
    cat > "$SYSTEMD_DIR/glitch-mpv-user.service" <<EOF
[Unit]
Description=Glitch Lamp lecture mpv (service utilisateur)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$ROOT_DIR
Environment=HOME=$HOME
ExecStart=/usr/bin/mpv --no-terminal --video-rotate=270 --fs --panscan=1.0 http://127.0.0.1:18000/stream/stream.m3u8
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
}

prompt_service_generation() {
    if [ ! -t 0 ]; then
        echo "Mode non interactif : aucun fichier .service généré."
        return
    fi

    echo
    echo "Génération optionnelle des fichiers systemd (.service) :"
    echo "  1) Aucun fichier (par défaut)"
    echo "  2) Machine kiosque : backend + mpv sur tty1 (root)"
    echo "  3) Session utilisateur : backend + mpv en user"
    read -r -p "Votre choix [1/2/3] : " service_choice

    case "$service_choice" in
        2)
            write_backend_service
            write_mpv_tty_service
            echo "Fichiers générés dans $SYSTEMD_DIR : glitch-backend.service, glitch-mpv.service"
            ;;
        3)
            write_backend_service
            write_mpv_user_service
            echo "Fichiers générés dans $SYSTEMD_DIR : glitch-backend.service, glitch-mpv-user.service"
            ;;
        *)
            echo "Aucun fichier .service généré."
            ;;
    esac
    echo "Copiez ou activez ensuite les services avec systemctl selon votre besoin."
}

echo "Installation des dépendances..."

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "Python3 est introuvable. Merci de l'installer."
    exit 1
fi

echo "Création de l'environnement virtuel..."
python3 -3.10 -m venv venv

echo "Activation de l'environnement virtuel..."
source venv/bin/activate

echo "Mise à jour de pip..."
pip install --upgrade pip

echo "Installation des dépendances Python..."
pip install -r requirements.txt

echo "Vérification de FFmpeg..."
if ! command -v ffmpeg &> /dev/null; then
    echo "AVERTISSEMENT : FFmpeg n'est pas installé ou absent du PATH."
    echo "Certaines fonctionnalités (datamosh, recompress) en dépendent."
    echo "Installez FFmpeg (ex. sudo apt install ffmpeg)."
else
    echo "FFmpeg détecté."
fi

prompt_service_generation

echo
echo "Résumé pour activer les services systemd :"
echo "  Fichiers générés dans : $SYSTEMD_DIR"
echo "  Option 2 (kiosque root) :"
echo "    sudo cp $SYSTEMD_DIR/glitch-backend.service /etc/systemd/system/"
echo "    sudo cp $SYSTEMD_DIR/glitch-mpv.service /etc/systemd/system/"
echo "    sudo systemctl daemon-reload"
echo "    sudo systemctl enable --now glitch-backend.service glitch-mpv.service"
echo "  Option 3 (session utilisateur) :"
echo "    sudo cp $SYSTEMD_DIR/glitch-backend.service /etc/systemd/system/"
echo "    mkdir -p ~/.config/systemd/user"
echo "    cp $SYSTEMD_DIR/glitch-mpv-user.service ~/.config/systemd/user/"
echo "    sudo systemctl daemon-reload"
echo "    systemctl --user daemon-reload"
echo "    sudo systemctl enable --now glitch-backend.service"
echo "    systemctl --user enable --now glitch-mpv-user.service"
echo

echo "Installation terminée."
