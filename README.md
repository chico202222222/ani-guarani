# ani-guarani

**Animes em português brasileiro, direto do terminal.**

O **ani-guarani** é uma continuação do [ani-tupi](https://github.com/eduardonery1/ani-tupi), criado originalmente por [Eduardo Nery](https://github.com/eduardonery1). O projeto original nasceu como uma alternativa para assistir a animes em português brasileiro pela linha de comando.

Esta nova versão é mantida por [chico202222222](https://github.com/chico202222222), no repositório [chico202222222/ani-guarani](https://github.com/chico202222222/ani-guarani), com foco em recuperar o funcionamento do código legado, melhorar a experiência no terminal e facilitar a manutenção das fontes de animes.

> Esta é uma continuação independente. O trabalho e a autoria do projeto original pertencem a Eduardo Nery e aos respectivos contribuidores; a manutenção desta versão não implica participação ou endosso do autor original.

## Objetivo da continuação

O foco desta versão é **animes**. A evolução do projeto está voltada a:

- Modernizar o código e reduzir dependências desnecessárias.
- Corrigir falhas na busca, na seleção de episódios e no histórico.
- Melhorar mensagens de progresso, erros e navegação no terminal.
- Tornar os plugins de fontes mais fáceis de manter.
- Facilitar a execução local e a geração de executáveis.

O projeto está em manutenção e refatoração. Algumas funcionalidades dependem de sites de terceiros e podem deixar de funcionar quando esses sites mudam. Não há garantia de disponibilidade de cada fonte.

## Como funciona

1. Você pesquisa um anime.
2. Os plugins consultam as fontes disponíveis e reúnem os resultados.
3. Você escolhe o anime e o episódio no menu.
4. O Firefox, controlado pelo Selenium em modo headless, tenta localizar o player.
5. O endereço encontrado é enviado ao **mpv** para reprodução.
6. Após o mpv encerrar sem erro, o episódio é registrado no histórico.

O registro indica o último episódio aberto com reprodução encerrada sem erro; não comprova que ele foi assistido até o fim.

### Fontes presentes no código

| Plugin | Site |
| --- | --- |
| `animefire` | `animefire.plus` |
| `animesonlinecc` | `animesonlinecc.to` |

A presença de um plugin não significa que ele tenha sido validado recentemente contra o site real. Um endereço de iframe também não é necessariamente um vídeo que o mpv consiga reproduzir.

As extensões do Mihon **não são compatíveis diretamente** com este projeto. Um sistema de instalação de extensões externas não está implementado.

## Requisitos

O fluxo principal de desenvolvimento e execução é voltado a **Linux**:

- Python **3.10 ou superior**, com `pip` e `venv`.
- Bash para os scripts `ani-guarani` e `build.sh`.
- **mpv**, disponível no `PATH`.
- **Firefox** para a resolução dos players.
- Conexão com a internet.

O Selenium pode precisar baixar o driver do navegador na primeira execução. Ambientes com Firefox instalado via Snap podem exigir configuração específica do `geckodriver`.

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip mpv firefox git
```

A disponibilidade e a forma de instalação do Firefox variam conforme a distribuição.

## Instalação pelo código-fonte

```bash
git clone https://github.com/chico202222222/ani-guarani.git
cd ani-guarani

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

chmod +x ani-guarani build.sh
./ani-guarani --help
```

O lançador procura o Python em `.venv/`, depois em `venv/` e, por último, usa `python3` do `PATH`. Não é necessário ativar o ambiente virtual.

Para escolher outro interpretador:

```bash
ANI_GUARANI_PYTHON=/caminho/para/python ./ani-guarani -q Naruto
```

O lançador não instala dependências automaticamente e não modifica o `~/.bashrc`.

### Comando disponível no PATH — opcional

Na raiz do repositório:

```bash
mkdir -p "$HOME/.local/bin"
ln -s "$PWD/ani-guarani" "$HOME/.local/bin/ani-guarani"
```

Certifique-se de que `~/.local/bin` esteja no seu `PATH`. Se já existir um arquivo ou link com esse nome, confira-o antes de substituir. O link depende de o repositório permanecer no mesmo local.

## Uso

### Busca interativa

```bash
./ani-guarani
```

### Buscar pelo nome

```bash
./ani-guarani -q "Naruto"
```

### Retomar pelo histórico

```bash
./ani-guarani --continue-watching
# Forma curta:
./ani-guarani -c
```

### Escolher a fonte

```bash
./ani-guarani -q "Naruto" --source animefire
```

Sem `--source`, todos os plugins disponíveis são considerados. A opção pode ser repetida para selecionar mais de uma fonte.

A restrição também vale ao retomar o histórico:

```bash
./ani-guarani -c --source animefire
```

Nesse caso, apenas episódios das fontes habilitadas entram na navegação. Se o episódio salvo não estiver disponível nelas, o programa orienta habilitar a fonte original ou fazer outra busca. As fontes desabilitadas são preservadas no arquivo de histórico.

### Diagnóstico e ajuda

```bash
./ani-guarani --debug -q "Naruto"
./ani-guarani --help
```

`--debug` habilita logs detalhados; não deve ser usado como simulação da reprodução. Os logs podem conter endereços dos players: revise-os antes de compartilhar.

### Navegação

- **↑ / ↓** ou **j / k**: mover a seleção.
- **Enter**: confirmar.
- **q**, **Esc** ou **Sair**: encerrar o menu.
- Em terminais sem suporte ao menu interativo, use as opções numeradas; **0** encerra.
- **Ctrl+C** interrompe a operação.

Para desabilitar as cores das mensagens de progresso:

```bash
NO_COLOR=1 ./ani-guarani -q "Naruto"
```

## Histórico

No Linux, o histórico é salvo em:

```text
${XDG_STATE_HOME:-~/.local/state}/ani-tupi/history.json
```

O nome `ani-tupi` foi mantido nesse diretório para preservar a leitura do histórico legado. As gravações usam substituição atômica para reduzir o risco de arquivos parcialmente escritos.

Se o histórico estiver inválido, o programa informa o problema em vez de sobrescrevê-lo silenciosamente. Faça uma cópia antes de editar ou renomear o arquivo.

## Gerar um executável

O PyInstaller é uma dependência de build, separada das dependências de execução:

```bash
.venv/bin/python -m pip install -r requirements-build.txt
./build.sh
```

O resultado esperado é:

```text
dist/ani-guarani
```

O build não altera o `PATH` nem os arquivos de configuração do shell. O executável deve ser gerado e testado no sistema de destino; um build Linux não gera automaticamente uma versão para Windows.

**Estado da validação:** o build foi iniciado durante a refatoração, mas interrompido antes da conclusão. A distribuição como executável ainda precisa de validação completa.

## Desenvolvimento e testes

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
bash -n ani-guarani build.sh
```

Os testes automatizados usam mocks para rede, navegador e reprodução. Eles verificam a lógica local, mas não garantem que os sites estejam acessíveis ou que seus players continuem compatíveis.

### Estrutura principal

```text
ani-guarani             Lançador Bash
main.py                 Argumentos e fluxo da CLI
menu.py                 Menu interativo e alternativa numerada
repository.py           Agregação e consulta concorrente de fontes
loader.py               Descoberta e carregamento de plugins locais
history.py              Leitura, validação e gravação do histórico
video_player.py         Integração com mpv
plugins/                Integrações com as fontes de animes
build.sh                Build com PyInstaller
requirements.txt        Dependências de execução
requirements-build.txt  Dependências de build
tests/                  Testes automatizados
```

Plugins Python executam código na sua máquina. Utilize apenas plugins revisados e de origem confiável.

## Limitações e uso responsável

- A reprodução real depende dos sites, dos seletores HTML, do Firefox e do mpv.
- Proteções anti-bot, mudanças de domínio e players incorporados podem impedir o funcionamento.
- Agregar fontes por posição pressupõe que suas listas de episódios tenham a mesma ordem; diferenças de especiais, temporadas ou dublagens podem exigir ajustes nos plugins.
- A resolução pode aguardar o encerramento dos outros navegadores mesmo após uma fonte encontrar um resultado.
- A gravação atômica do histórico não evita conflitos entre duas instâncias abertas ao mesmo tempo.
- O lançador Bash e a execução gráfica no Windows não foram validados nesta continuação.
- As dependências têm faixas de versões, não um lock reproduzível. Uma auditoria de segurança das dependências ainda é necessária antes de distribuir releases.
- O projeto não hospeda os vídeos. Use apenas conteúdo que você tenha autorização para acessar e respeite a legislação e os termos dos serviços consultados.

## Créditos

- **Projeto original:** [ani-tupi](https://github.com/eduardonery1/ani-tupi).
- **Autor original:** [Eduardo Nery — eduardonery1](https://github.com/eduardonery1).
- **Continuação e manutenção do ani-guarani:** [chico202222222](https://github.com/chico202222222).
- Agradecimentos aos demais contribuidores do projeto original e desta continuação.

### Demonstração do projeto original

A demonstração abaixo pertence ao projeto original e pode não refletir a interface ou a compatibilidade atual:

[![Demonstração original do ani-tupi](https://img.youtube.com/vi/eug6gKLTD3I/maxresdefault.jpg)](https://youtu.be/eug6gKLTD3I)

## Licença

Este projeto preserva a **Mozilla Public License 2.0 (MPL-2.0)** do projeto original. Consulte o texto completo em [LICENSE](LICENSE).

Ao redistribuir ou modificar o projeto, preserve os avisos de licença e autoria aplicáveis e cumpra os termos da MPL-2.0. A continuação sob outro nome não remove os direitos nem os créditos do autor original.
