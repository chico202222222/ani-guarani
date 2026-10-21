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
4. O AnimeFire consulta sua API JSON; o AnimesOnlineCloud extrai os servidores do HTML e da API DooPlay e testa um por um; AnimesDigital e AniTube leem o player HLS (`api.anivideo.net`) da página do episódio; o AnimesOnlineCC usa Firefox/Selenium em modo headless.
5. O endereço encontrado é enviado ao **mpv**. Para o CDN do AnimeFire, um relay HLS temporário em `127.0.0.1` normaliza as playlists e os tipos de conteúdo.
6. Após o mpv encerrar sem erro, o episódio é registrado no histórico.

O registro indica o último episódio aberto com reprodução encerrada sem erro; não comprova que ele foi assistido até o fim.

### Fontes presentes no código

| Plugin | Site |
| --- | --- |
| `animefire` | `animefire.one` / API `api.animefire.one` |
| `animesonlinecc` | `animesonlinecc.to` |
| `animesonlinecloud` | `animesonline.cloud` |
| `animesdigital` | `animesdigital.org` |
| `anitube` | `www.anitube.zip` |

Estado verificado em **21/10/2026**:

| Fonte | Busca | Reprodução |
| --- | --- | --- |
| `animesdigital` | OK | OK (HLS, 720p H.264/AAC), legendado e dublado; testado em *Jujutsu Kaisen* (T1 completa) e *One Piece* (1180 episódios) |
| `anitube` | OK | OK (mesmo CDN HLS do `animesdigital`); testado em *Jujutsu Kaisen* e *One Piece* |
| `animesonlinecloud` | OK | Parcial: cada episódio tem vários servidores (Blogger, MP4, ...) e o plugin usa o primeiro que responde. Há episódios em que todos estão fora do ar (ex.: *Jujutsu Kaisen* ep. 2) |
| `animesonlinecc` | OK | OK (Blogger, H.264/AAC 360p); exige Firefox |
| `animefire` | OK | **Indisponível**: o CDN responde 404 para todos os streams (veja abaixo) |

A presença de um plugin não significa que ele tenha sido validado recentemente contra o site real. Um endereço de iframe também não é necessariamente um vídeo que o mpv consiga reproduzir.

### Adaptação do repositório Yūzōnō

O conector `animefire` foi atualizado com base na extensão do [yuzono/anime-extensions](https://github.com/yuzono/anime-extensions), revisão `ee94f0850f42f3becefeab01a0bc53033e8b52ff`. A adaptação usa os endpoints da API v3 para busca, episódios e streams, substituindo o antigo scraper de `animefire.plus`.

```bash
./ani-guarani --source animefire -q "Naruto"
```

- Não exige Firefox para essa fonte.
- Os resultados exibem `[AnimeFire: ID]`, evitando mesclar listas de temporadas/fontes diferentes pelo mesmo título.
- Episódios são apresentados em ordem crescente de temporada e número.
- O áudio preferido nesta adaptação é legendado, priorizando traduções não automáticas; dublado é usado quando não há candidato legendado equivalente.
- Links antigos do AnimeFire no histórico precisam de uma nova busca; não são convertidos automaticamente.
- O relay só acessa HTTPS `akumast.net/i/`, verifica certificados, restringe redirects e encerra ao fechar o player. Não é uma API pública nem um proxy para hosts arbitrários.
- O relay HLS não reproduz o servidor DASH/separador fMP4 do Android. Reprodução e seek dependem da compatibilidade do mpv/FFmpeg.

**Validação real:** a busca por Naruto e sua lista de 219 episódios responderam na API durante a integração. Os dois streams do primeiro episódio responderam HTTP 404 no CDN; portanto, não foi possível confirmar reprodução real dessa fonte. A aplicação informa esse erro antes de iniciar o mpv.

**Reverificação (21/10/2026):** 16 streams de 8 animes diferentes (One Piece, Dragon Ball, Jujutsu Kaisen, Bleach, Frieren etc.) responderam 404 do nginx de origem. O resultado foi o mesmo com `curl`, HTTP/1.1 e HTTP/2, vários `User-Agent` e mais de 40 perfis de impersonação TLS de navegadores (`curl_cffi`). Portanto, não é bloqueio por fingerprint TLS nem por cabeçalhos; a origem não serve os arquivos. A revisão upstream usada aqui já é mais recente que o último commit do conector no repositório consultado, então não há correção disponível por lá. Por isso o AnimeFire é a última opção do fallback.

#### Animes Online Cloud: alternativa validada

Também foi adaptada a fonte **AnimesOnlineCloud** do mesmo repositório, com suporte ao HTML atual, que difere dos seletores da extensão consultada:

```bash
./ani-guarani --source animesonlinecloud -q "Jujutsu Kaisen"
```

Selecione **Jujutsu Kaisen: Shimetsu Kaiyuu – Zenpen Dublado [AnimesOnlineCloud]**. Durante a validação, a busca retornou esse anime, a lista trouxe 12 episódios e o primeiro resolveu para um MP4 acessível. Um teste curto de decodificação real no mpv identificou vídeo H.264 1080p e áudio AAC; não foi assistido o episódio completo.

Essa fonte não abre Firefox. Suporta `video`/`source` no HTML atual e fallback para a API DooPlay, Blogger e links `jwplayer?source=` conhecidos. O mpv envia o `Referer` do provedor aos CDNs confirmados `aniplay.online` e `mangas.cloud`, pois a mídia testada retorna 403 sem esse cabeçalho. Nem todo anime foi validado: os links de Naruto (clássico) e do episódio 1 de One Piece retornam 404 no CDN `mangas.cloud`. Antes de abrir o mpv, o ani-guarani confere os CDNs `aniplay.online` e `mangas.cloud` e, se a mídia responder 404/410, falha com uma mensagem clara e tenta a próxima fonte. O site também devolve uma busca vazia para alguns termos capitalizados (ex.: "Jujutsu Kaisen"); nesse caso a busca é repetida em minúsculas.

Sobre o **AnimeFire**, o próprio servidor upstream documenta dependência da pilha TLS Android/OkHttp. A adaptação Python não reproduz essa pilha; o HTTP 404 observado não comprova, sozinho, que o arquivo foi removido. Não desligamos a verificação TLS nem alteramos URLs por tentativa.

Este projeto **não executa APKs** e não suporta automaticamente todas as extensões do Anikku/Aniyomi/Mihon. Cada conector precisa de adaptação para Python. Não há download nem execução automática de código do repositório externo. Veja os créditos e termos em [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

### Ordem das fontes e fallback

As fontes são tentadas em ordem de confiabilidade (`animesonlinecloud` → `animesonlinecc` → `animesdigital` → `anitube` → `animefire`). Esse fallback só acontece entre fontes que compartilham o mesmo título; como os resultados levam o nome da fonte (`[AniTube]`, `[AnimesDigital]`), se uma fonte falhar escolha o mesmo anime em outra. Se uma não resolver ou o mpv falhar, a próxima é tentada automaticamente. Resultados de busca que não contêm os termos pesquisados são ocultados quando há correspondências melhores. Filmes/OVAs do AnimesOnlineCloud aparecem como um único item "Filme".

## Requisitos

O fluxo principal de desenvolvimento e execução é voltado a **Linux**:

- Python **3.10 ou superior**, com `pip` e `venv`.
- Bash para os scripts `ani-guarani` e `scripts/build.sh`.
- **mpv**, disponível no `PATH`.
- **yt-dlp**, instalado via `requirements.txt`, para extrair vídeos de players incorporados.
- **Firefox** para a fonte `animesonlinecc` (dispensável ao usar somente `--source animefire` ou `--source animesonlinecloud`).
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

chmod +x ani-guarani scripts/build.sh
./ani-guarani --help
```

O lançador procura o Python em `.venv/`, depois em `venv/` e, por último, usa `python3` do `PATH`. Não é necessário ativar o ambiente virtual. Na instalação acima, o diretório é `.venv` (com ponto), não `venv`. Se preferir ativá-lo, use `source .venv/bin/activate` no Bash/Zsh ou `source .venv/bin/activate.fish` no Fish.

Para escolher outro interpretador:

```bash
ANI_GUARANI_PYTHON=/caminho/para/python ./ani-guarani -q Naruto
```

O lançador não instala dependências automaticamente e não modifica o `~/.bashrc`.

### Erros do `ytdl_hook` / Blogger

O projeto resolve diretamente as URLs de mídia presentes no atributo estruturado `data-p` do novo player do Blogger. Páginas antigas ou layouts desconhecidos continuam delegados ao `yt-dlp`. Quando o Blogger responde explicitamente `Video is unavailable`, a fonte é rejeitada com uma mensagem descritiva, sem enviar essa página de erro ao mpv.

Se o mpv ainda mostrar `Unable to extract JSON data` ou `youtube-dl failed`, confira se o extrator está atualizado:

```bash
.venv/bin/python -m pip install --upgrade yt-dlp
.venv/bin/yt-dlp --version
./ani-guarani --debug -q "Jujutsu Kaisen"
```

O programa prefere o `yt-dlp` instalado junto do interpretador em uso e informa seu caminho no modo `--debug`. Assim, não depende do extrator potencialmente antigo fornecido pela distribuição, mesmo sem ativar o ambiente virtual. Em builds distribuídos, o executável `yt-dlp` deve estar disponível no `PATH` se não existir ao lado do interpretador/executável da aplicação.

**403 em `googlevideo.com`:** o Blogger assina a URL do vídeo para o `User-Agent` que abriu a página do player. A página agora é obtida com um `User-Agent` de navegador e o mesmo valor é repassado ao mpv (`--user-agent`), o que corrigiu o HTTP 403 do AnimesOnlineCC. Quando há vários formatos, o de melhor qualidade é escolhido (mp4 `itag` 22/18 antes de 3GPP).

Atualizar o extrator não garante suporte a todos os players: o vídeo pode estar removido, exigir autenticação ou usar um formato ainda incompatível.

### Comando disponível no PATH — opcional

Na raiz do repositório:

```bash
mkdir -p "$HOME/.local/bin"
ln -s "$PWD/ani-guarani" "$HOME/.local/bin/ani-guarani"
```

Certifique-se de que `~/.local/bin` esteja no seu `PATH`. Se já existir um arquivo ou link com esse nome, confira-o antes de substituir. O link depende de o repositório permanecer no mesmo local.

## Docker

A imagem inclui Python, mpv, Firefox ESR e o geckodriver (baixado na construção), sem instalar nada no host. O histórico fica no volume `ani-guarani-data` (`/data`).

```bash
# 1. Construir a imagem
docker compose build        # ou: make docker

# 2. Permitir que o contêiner abra janelas no seu X11 (revogue depois)
xhost +local:docker

# 3. Executar
docker compose run --rm ani-guarani -q "Jujutsu Kaisen" --source animesonlinecloud
# ou: make docker-run ARGS='-q "Naruto"'

xhost -local:docker
```

- **Vídeo:** usa o socket X11 do host (`/tmp/.X11-unix`) e `/dev/dri` para aceleração. Remova o bloco `devices` do `docker-compose.yml` se o host não tiver `/dev/dri`.
- **Áudio:** usa o socket PulseAudio/PipeWire-Pulse em `$XDG_RUNTIME_DIR/pulse/native`.
- **Usuário:** o contêiner roda sem root com UID/GID 1000. Para outro usuário: `UID=$(id -u) GID=$(id -g) docker compose build`.
- **Sem Docker Compose:** `docker build -t ani-guarani .` e `docker run --rm -it -v ani-guarani-data:/data ani-guarani --help`. Sem tela/áudio configurados, a busca e a navegação funcionam, mas a reprodução não.
- Wayland puro (sem XWayland) e macOS/Windows não foram validados. A reprodução real dentro do contêiner depende da sua configuração gráfica e de áudio; neste ambiente foram validadas a construção da imagem e a busca.

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

### Lista para assistir

Guarde animes para ver depois, separadamente do histórico:

```bash
# Salvar sem reproduzir (escolha o anime no menu)
./ani-guarani -q "Hunter x Hunter" --add-watchlist     # ou: -a

# Abrir a lista (mostra o progresso do histórico de cada anime)
./ani-guarani --watchlist                              # ou: -l
```

- Ao escolher um item da lista, você pode **Assistir** (retoma do último episódio aberto no histórico ou do episódio 1) ou **Remover da lista**.
- Depois de cada episódio, o menu também oferece **Adicionar à / Remover da lista para assistir**.
- A lista guarda as fontes e os episódios encontrados, então abrir um item não exige nova busca. Como no histórico, `--source` restringe só a reprodução; se nenhuma fonte salva estiver habilitada, o programa avisa.
- `--watchlist` não pode ser combinado com `--query`, `--continue-watching` ou `--add-watchlist`.

### Legendado ou dublado

Quando a busca traz os dois tipos, o programa pergunta `Legendado / Dublado / Todos` antes de listar os animes. Para pular a pergunta:

```bash
./ani-guarani -q "Jujutsu Kaisen" --audio dublado    # ou: legendado, todos
```

- `AnimesDigital`, `AniTube` e `AnimesOnlineCloud` publicam legendado e dublado como títulos separados; o tipo vem da etiqueta do site (AniTube) ou do "Dublado" no título. Sem marcação, é legendado.
- O AnimeFire informa os áudios de cada anime e traz as duas faixas no mesmo episódio; com `--audio`, o stream escolhido segue sua preferência. Se o episódio não tiver essa faixa, a fonte falha em vez de trocar o áudio em silêncio.
- `--audio` vale para buscas (`-q`); ao retomar pelo histórico (`-c`) ou pela lista (`-l`) vale o anime salvo.

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

No Docker, `XDG_STATE_HOME=/data`, então o arquivo fica em `/data/ani-tupi/history.json`, dentro do volume `ani-guarani-data`.

A lista para assistir fica no mesmo diretório, em `watchlist.json`. O nome `ani-tupi` foi mantido nesse diretório para preservar a leitura do histórico legado. As gravações usam substituição atômica para reduzir o risco de arquivos parcialmente escritos.

Se o histórico estiver inválido, o programa informa o problema em vez de sobrescrevê-lo silenciosamente. Faça uma cópia antes de editar ou renomear o arquivo.

## Gerar um executável

O PyInstaller é uma dependência de build, separada das dependências de execução:

```bash
.venv/bin/python -m pip install -r requirements-build.txt
./scripts/build.sh   # ou: make build
```

O resultado esperado é:

```text
dist/ani-guarani
```

O build não altera o `PATH` nem os arquivos de configuração do shell. O executável deve ser gerado e testado no sistema de destino; um build Linux não gera automaticamente uma versão para Windows.

O build foi validado localmente com execução de `dist/ani-guarani --help` e verificação da presença dos módulos Firefox do Selenium no executável. O build inclui esses imports dinâmicos explicitamente, além das licenças e dos avisos de terceiros. A reprodução completa e o navegador dentro do executável ainda precisam de validação no sistema de destino.

## Desenvolvimento e testes

```bash
.venv/bin/python -m unittest discover -s tests -v   # ou: make test
.venv/bin/python -m pip check
bash -n ani-guarani scripts/build.sh
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
watchlist.py            Lista para assistir (watchlist.json)
video_player.py         Integração com mpv
stream_proxy.py         Relay HLS local restrito ao CDN do AnimeFire
plugins/                Integrações com as fontes de animes
  animefire.py          API v3 do AnimeFire
  animesonlinecloud.py  HTML + API DooPlay
  animesdigital.py      HTML + player HLS api.anivideo.net
  anitube.py            HTML + player HLS api.anivideo.net
  animesonlinecc.py     Selenium/Firefox
  utils.py              Selenium, Blogger e utilidades comuns
tests/                  Testes automatizados
scripts/build.sh        Build com PyInstaller
docs/                   Notas de desenvolvimento (todo.txt)
LICENSES/, THIRD_PARTY_NOTICES.md   Licenças e atribuições
Dockerfile, docker-compose.yml, .dockerignore   Contêiner
Makefile                Atalhos: install, test, run, build, docker
requirements.txt        Dependências de execução
requirements-build.txt  Dependências de build
```

Plugins Python executam código na sua máquina. Utilize apenas plugins revisados e de origem confiável.

## Limitações e uso responsável

- A reprodução real depende dos sites/APIs, do CDN e do mpv; o AnimesOnlineCC também depende de seletores HTML e Firefox. O AnimeFire está sem reprodução enquanto o CDN responder 404.
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
- **Referência dos conectores AnimeFire e AnimesOnlineCloud:** [yuzono/anime-extensions](https://github.com/yuzono/anime-extensions), Javier Tomás e os contribuidores upstream, sob Apache-2.0.
- Agradecimentos aos demais contribuidores do projeto original e desta continuação.

### Demonstração do projeto original

A demonstração abaixo pertence ao projeto original e pode não refletir a interface ou a compatibilidade atual:

[![Demonstração original do ani-tupi](https://img.youtube.com/vi/eug6gKLTD3I/maxresdefault.jpg)](https://youtu.be/eug6gKLTD3I)

## Licença

Este projeto preserva a **Mozilla Public License 2.0 (MPL-2.0)** do projeto original. Consulte o texto completo em [LICENSE](LICENSE).

Os conectores adaptados `plugins/animefire.py` e `plugins/animesonlinecloud.py` mantêm sua identificação **Apache-2.0**. A licença desses componentes está em [LICENSES/Apache-2.0.txt](LICENSES/Apache-2.0.txt), com atribuição e descrição das alterações em [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Isso não substitui a licença do restante do projeto.

Ao redistribuir ou modificar o projeto, preserve os avisos de licença e autoria aplicáveis e cumpra os termos da MPL-2.0. A continuação sob outro nome não remove os direitos nem os créditos do autor original.
