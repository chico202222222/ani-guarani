# Third-party notices

## Yūzōnō / Anikku / Aniyomi anime extensions

- Projeto: https://github.com/yuzono/anime-extensions
- Revisão consultada: `ee94f0850f42f3becefeab01a0bc53033e8b52ff`
- Arquivos de referência:
  - `src/pt/animefire/src/eu/kanade/tachiyomi/animeextension/pt/animefire/AnimeFire.kt`
  - `src/pt/animefire/src/eu/kanade/tachiyomi/animeextension/pt/animefire/dto/AnimeFireDto.kt`
  - `src/pt/animesonlinecloud/src/eu/kanade/tachiyomi/animeextension/pt/animesonlinecloud/AnimesOnlineCloud.kt`
- Copyright 2015 Javier Tomás, conforme aviso no README upstream.
- Créditos adicionais: yuzono e demais contribuidores do repositório upstream.
- Licença: Apache License, Version 2.0. Texto preservado integralmente em
  [`LICENSES/Apache-2.0.txt`](LICENSES/Apache-2.0.txt).

`plugins/animefire.py` é uma **adaptação modificada em Python**, não uma cópia
executável da extensão Android. A adaptação mantém os endpoints e o contrato de
dados como referência, adiciona validação de respostas, usa a interface local de
plugins e apresenta episódios em ordem crescente. O arquivo mantém sua
identificação Apache-2.0.

`plugins/animesonlinecloud.py` é outra **adaptação modificada em Python**, baseada
na fonte AnimesOnlineCloud do mesmo projeto. Mantém a referência ao endpoint
DooPlay, acrescenta suporte ao HTML atual (`episode-card`, `video` e `source`),
validação de redirecionamentos, ordenação numérica e integração com o resolvedor
Blogger local. Não executa JavaScript ou APKs. Esse arquivo também mantém sua
identificação Apache-2.0.

O relay `stream_proxy.py` é uma implementação local para normalizar playlists HLS
para o mpv. Não reproduz o servidor DASH nem o separador de tracks fMP4 do Android.
Não há promessa de equivalência com o player Anikku/Aniyomi, especialmente para
seek, codecs e versões diferentes do FFmpeg.

Não são instalados, executados nem atualizados APKs desse repositório. Não há
vínculo ou endosso de seus mantenedores a esta adaptação.

## Projeto original ani-tupi

O projeto ani-guarani continua o trabalho de Eduardo Nery:
https://github.com/eduardonery1/ani-tupi

O arquivo `LICENSE` original, Mozilla Public License 2.0, foi preservado.
A inclusão do componente Apache-2.0 acima não substitui essa licença nem os
créditos do projeto original. As dependências Python possuem suas próprias
licenças, que também devem ser respeitadas ao distribuir executáveis.
