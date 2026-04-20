# Jukebox Pi — dev machine targets
# Requires .env with JUKEBOX_USER, JUKEBOX_HOST, etc.

include .env
export

HOST := $(JUKEBOX_USER)@$(JUKEBOX_HOST)
REMOTE_DIR := /opt/jukebox
TMP_DIR := /tmp/jukebox-deploy

.PHONY: help build deploy setup pair logs status restart reboot ssh

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' Makefile | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

build: ## Bundle JS modules with esbuild
	@npm run build --prefix web

deploy: build ## Build + deploy web dashboard to the Pi
	@echo "==> Uploading to $(HOST):$(TMP_DIR)"
	@ssh $(HOST) "rm -rf $(TMP_DIR) && mkdir -p $(TMP_DIR)/templates $(TMP_DIR)/static $(TMP_DIR)/routes"
	@scp -q web/app.py web/helpers.py web/cava.conf $(HOST):$(TMP_DIR)/
	@scp -q web/routes/*.py                         $(HOST):$(TMP_DIR)/routes/
	@scp -q web/static/style.css web/static/app.js  $(HOST):$(TMP_DIR)/static/
	@scp -q web/templates/index.html                $(HOST):$(TMP_DIR)/templates/
	@echo "==> Deploying to $(REMOTE_DIR)"
	@ssh $(HOST) "\
		sudo rm -rf $(REMOTE_DIR)/__pycache__ $(REMOTE_DIR)/routes/__pycache__ && \
		sudo cp -r $(TMP_DIR)/* $(REMOTE_DIR)/ && \
		sudo systemctl restart jukebox-web && \
		rm -rf $(TMP_DIR)"
	@ssh $(HOST) "sudo systemctl is-active jukebox-web"
	@echo "==> Done — http://$(JUKEBOX_HOST):5000"

setup: ## Copy scripts + .env to Pi and run setup.sh
	@echo "==> Uploading setup files to $(HOST)"
	@scp .env scripts/setup.sh scripts/pair-bt.sh $(HOST):~
	@echo "==> Running setup.sh"
	@ssh $(HOST) "chmod +x setup.sh pair-bt.sh && sudo ./setup.sh"

pair: ## Run pair-bt.sh on the Pi (speaker must be in pairing mode)
	@ssh $(HOST) "sudo ./pair-bt.sh"

logs: ## Tail service logs on the Pi
	@ssh $(HOST) "sudo journalctl -u jukebox-web -u snapclient -u bt-autoconnect -f --no-pager -n 30"

status: ## Show service status on the Pi
	@ssh $(HOST) "\
		echo '--- Services ---' && \
		sudo systemctl is-active snapclient bt-autoconnect jukebox-web wifi-roam && \
		echo '--- Bluetooth ---' && \
		bluetoothctl info $(BT_MAC) 2>/dev/null | grep -E 'Name:|Connected:' && \
		echo '--- Snapcast ---' && \
		curl -s -m 3 -X POST -H 'Content-Type: application/json' \
			-d '{\"id\":1,\"jsonrpc\":\"2.0\",\"method\":\"Server.GetStatus\"}' \
			http://$(SNAPCAST_SERVER):1780/jsonrpc 2>/dev/null \
			| python3 -c 'import sys,json; d=json.load(sys.stdin); [print(f\"  {c[\"host\"][\"name\"]}: connected={c[\"connected\"]}\") for g in d[\"result\"][\"server\"][\"groups\"] for c in g[\"clients\"]]' \
			|| echo '  unreachable'"

restart: ## Restart all jukebox services
	@ssh $(HOST) "sudo systemctl restart snapclient bt-autoconnect jukebox-web"
	@echo "==> Restarted"

reboot: ## Reboot the Pi
	@ssh $(HOST) "sudo reboot" || true
	@echo "==> Rebooting..."

ssh: ## Open SSH session to the Pi
	@ssh $(HOST)
