# Prompt Cursor — installer le worker GPU sur le PC Windows

Copie le bloc ci-dessous dans une nouvelle conversation Cursor **sur le PC Windows**, après avoir ouvert le dossier du repo cloné dans WSL (`~/auto-trad-ytb`). Remplace `MAC_HOST_IP` par l’IP affichée sur le Mac par `./scripts/mac-host-gpu-worker.sh`.

---

```text
Tu es sur un PC Windows avec une carte NVIDIA (~16 Go VRAM). Ce repo est un monorepo de doublage vidéo (auto-trad-ytb).

Objectif : installer et lancer UNIQUEMENT le worker Celery GPU, qui consomme les jobs du Mac. Le Mac garde déjà web, API, Postgres, Redis, S3 (LocalStack) et Ollama (rewrite qwen3.8:27b). Ne lance PAS postgres/redis/api/web/ollama ici.

Adresse du Mac (LAN ou Tailscale) : MAC_HOST_IP

Suis docs/gpu-worker-windows.md et AGENTS.md / .cursor/rules (surtout voice-cloning : OmniVoice clone chaque speaker, jamais de fallback edge-tts/espeak).

Fais, dans l’ordre, et arrête-toi si une étape échoue avec un message clair :

1) Vérifie l’environnement
   - On doit être dans WSL2 Ubuntu (pas PowerShell seul), repo dans ~/… (pas /mnt/c/…).
   - `nvidia-smi` fonctionne dans WSL.
   - Docker Desktop est installé, moteur WSL2, et :
     `docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi`
     affiche la carte. Si ça échoue, installe/configure pilote NVIDIA + WSL2 + Docker Desktop GPU, puis relance.

2) Clone / sync
   - Si le dossier n’est pas déjà le repo : clone depuis GitHub dans ~/auto-trad-ytb.
   - Pas besoin de node_modules ni de .venv Python sur ce PC.

3) Lance le worker GPU
   - Depuis la racine du repo :
     MAC_HOST=MAC_HOST_IP docker compose -f docker-compose.gpu-worker.yml up --build
   - Le premier build télécharge PyTorch CUDA (long). Attends jusqu’aux logs :
     - `OmniVoice device: cuda:0 …`
     - Postgres / Redis / S3 reachable at MAC_HOST…
   - Si CUDA n’est pas visible, le script doit exit (ne pas laisser tourner sur CPU).
   - Si le Mac est injoignable, dis-moi quoi ouvrir côté Mac (pare-feu, OLLAMA_HOST=0.0.0.0, stack mac-host).

4) Ne change PAS le code sauf bug bloquant d’install. Ne retire pas le path OmniVoice. Ne mets pas Ollama sur ce PC sauf si je le demande. Ne commit / push rien sans mon OK.

Quand c’est up, résume en 5 lignes : IP utilisée, GPU détecté, commande exacte qui tourne, et comment relancer après reboot.
```

---

## Côté Mac (toi, avant le prompt)

```bash
# Ollama joignable depuis le réseau (une fois par session / reboot)
launchctl setenv OLLAMA_HOST 0.0.0.0:11434
open -a Ollama

# Stack sans worker local
./scripts/mac-host-gpu-worker.sh
```

Note l’IP affichée et remplace `MAC_HOST_IP` dans le prompt.
