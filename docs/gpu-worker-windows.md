# Worker GPU sur un PC Windows

Le Mac garde le site, l'API, Postgres, Redis, le stockage S3 et Ollama (réécriture avec `qwen3.8:27b` sur Metal). Le PC Windows fait tourner le worker Celery sur sa carte NVIDIA : clonage des voix avec OmniVoice, séparation de la musique avec Demucs et transcription avec Whisper.

```text
Mac  : web :3000, api :8000, postgres :5432, redis :6379, s3 :4566, ollama :11434
         ▲  réseau local ou Tailscale
PC   : worker-gpu (Docker Desktop + WSL2 + CUDA)
```

Le worker du PC va chercher les jobs dans le Redis du Mac. Il lit et écrit les fichiers dans le S3 du Mac et met à jour les étapes dans le Postgres du Mac. Le bouton Annuler marche toujours, parce que l'ordre d'arrêt passe aussi par Redis.

Le clonage reste le même : chaque ligne est dite par OmniVoice à partir de l'extrait de la personne qui l'a prononcée. Seul le matériel change.

## 1. Préparer le PC (une seule fois)

1. Installe le dernier pilote NVIDIA Game Ready ou Studio (version 570 ou plus récente).
2. Dans PowerShell en administrateur, lance `wsl --install`, puis redémarre.
3. Installe [Docker Desktop](https://www.docker.com/products/docker-desktop/). Dans Settings > General, coche *Use the WSL 2 based engine*.
4. Vérifie que Docker voit la carte :

   ```powershell
   docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi
   ```

   Le tableau doit afficher ta carte et ses 16 Go.

5. Copie le repo dans le système de fichiers WSL, par exemple `~/auto-trad-ytb` dans le terminal Ubuntu. Évite `C:\`, où les fichiers sont beaucoup plus lents depuis Docker. Les dossiers `node_modules`, `.venv` et `.next` ne sont pas nécessaires sur le PC.

## 2. Préparer le Mac

Ollama doit écouter sur le réseau, pas seulement sur `127.0.0.1`. Quitte l'application Ollama, puis :

```bash
launchctl setenv OLLAMA_HOST 0.0.0.0:11434
open -a Ollama
```

Ce réglage tient jusqu'au prochain redémarrage du Mac.

Ensuite, à la racine du repo :

```bash
./scripts/mac-host-gpu-worker.sh
```

Le script :

- refuse de continuer si un worker Celery tourne encore sur le Mac (`worker-mac.sh` ou `dev.sh`) ;
- arrête le `worker` du compose, et aussi son `ollama`, qui n'a que le modèle 0.5B ;
- lance `postgres`, `redis`, `s3`, `api` et `web` ;
- vérifie qu'Ollama écoute sur le réseau et que `qwen3.8:27b` est installé ;
- affiche l'adresse du Mac et la commande à lancer sur le PC.

Si macOS demande d'autoriser les connexions entrantes pour Docker ou Ollama, accepte.

## 3. Lancer le worker sur le PC

Dans le terminal Ubuntu (WSL), à la racine du repo :

```bash
MAC_HOST=192.168.1.20 docker compose -f docker-compose.gpu-worker.yml up --build
```

Remplace `192.168.1.20` par l'adresse affichée par le script du Mac. Le premier build télécharge PyTorch CUDA, ce qui prend plusieurs minutes. Le premier job télécharge aussi les modèles (OmniVoice, Whisper, Demucs) dans un volume Docker qui reste en place d'un lancement à l'autre.

Au démarrage, le worker affiche :

```text
OmniVoice device: cuda:0 NVIDIA GeForce ..., 16.0 GiB
Postgres reachable at 192.168.1.20:5432
Redis reachable at 192.168.1.20:6379
S3 reachable at 192.168.1.20:4566
```

S'il ne voit pas la carte, il s'arrête au lieu de cloner les voix sur le processeur. S'il ne joint pas le Mac, il s'arrête aussi et Docker le relance jusqu'à ce que le Mac réponde.

Lance ensuite un doublage depuis http://localhost:3000 sur le Mac. Les étapes s'affichent dans les logs du PC.

## Le code change

Le code est monté dans le conteneur. Après avoir recopié le repo sur le PC, `docker compose -f docker-compose.gpu-worker.yml restart` suffit. Il ne faut relancer `--build` que si `services/worker/requirements.txt` ou `Dockerfile.gpu` changent.

## Si le PC n'est pas sur le même réseau

Installe [Tailscale](https://tailscale.com) sur les deux machines et connecte-les au même compte. Utilise ensuite l'adresse Tailscale du Mac (`tailscale ip -4`, en `100.x.y.z`) comme `MAC_HOST`. N'ouvre jamais ces ports sur Internet depuis ta box : Redis n'a pas de mot de passe et Postgres utilise celui du dev.

## Réglages

| Variable | Défaut sur le PC | Effet |
|---|---|---|
| `WHISPER_MODEL` | `small` | `large-v3` tient dans 16 Go et transcrit mieux, mais plus lentement |
| `WHISPER_DEVICE` | `cuda` | Si les bibliothèques CUDA manquent, Whisper repasse sur le processeur avec un avertissement dans les logs |

OmniVoice et Demucs prennent CUDA automatiquement dès que PyTorch voit la carte.

## Revenir au Mac seul

Arrête le worker du PC (`docker compose -f docker-compose.gpu-worker.yml down`), puis relance `./scripts/worker-mac.sh` ou `docker compose up -d worker` sur le Mac.
