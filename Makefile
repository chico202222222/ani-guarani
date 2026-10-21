# Atalhos de desenvolvimento. Use `make help` para listar.
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: help install test run build docker docker-run

help:  ## Lista os comandos
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install:  ## Cria .venv e instala as dependências
	python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt

test:  ## Executa a suíte de testes
	$(PYTHON) -m unittest discover -s tests

run:  ## Executa a aplicação (ex.: make run ARGS='-q Naruto')
	$(PYTHON) main.py $(ARGS)

build:  ## Gera o executável com PyInstaller
	./scripts/build.sh

docker:  ## Constrói a imagem Docker
	docker compose build

docker-run:  ## Executa no Docker (ex.: make docker-run ARGS='-q Naruto')
	docker compose run --rm ani-guarani $(ARGS)
