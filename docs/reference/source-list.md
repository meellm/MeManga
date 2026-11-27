<!-- Written by python -m memanga.source_docs; do not edit. -->

## At a glance

| | |
|---|---|
| Sources (one scraper each) | 237 |
| Domains, with other domains of the same source | 302 |
| Included in search | 140 |
| In the default selection | 5 |
| Adult content | 24 |
| With parser tests of their own | 86 |
| With tests of a shared parser only | 90 |
| In the weekly live probe | 26 |
| Live probe through to an image download | 24 |

## Adult sources

::: warning Adult content
24 sources serve adult content. They are marked **Yes** in the **Adult** column below. MeManga does not hide or filter them.

- **Desktop app:** the default selection includes none of them. The **Sources** page does not mark adult sources, so check this list before you turn a source on.
- **Command line:** while [`sources.disabled`](./config#sources-disabled) is missing, `memanga search` asks the default selection and the sources in your library. A saved list turns off only the sources on it, so an empty list asks every source that is included in search, and that includes `bluesolo.org`, `dynasty-scans.com`, `e-hentai.org`, `furyosociety.com`, `hentai20.io`, `hentaifox.com`, `hentairead.com`, `imhentai.xxx`, `inventariooculto.com`, `lelscanfr.com`, `mangahome.com`, `mangarw.com`, `mangavault.lat`, `manytoon.com`, `nhentai.net`, `noranofansub.com`, `punkrecordz.com`, `rakuentranslations.com`, `rawkuma.net`, `rawuwu.net`, `yuri-online.com`. Use `memanga search --source DOMAIN` to ask one source only.
:::

## Default selection

These 5 sources are the default search selection. The first time the desktop app starts, it turns them on and turns off the others, apart from template sites, unless a selection is already saved in [`sources.disabled`](./config#sources-disabled). While that setting is missing, `memanga search` asks them and the sources in your library. They are searched in this order, and results from earlier sources are listed first.

| Source | Notes |
|---|---|
| mangadex.org | Fan-translation library |
| mangapark.cc | General library |
| mangafire.to | General library |
| mangabuddy.com | General library |
| weebcentral.com | General library |

## Why a source is not searched

| Search status | Reason |
|---|---|
| Not searched (template) | The site is built on one of MeManga's shared site templates, which search leaves out unless you follow a series from the site; most of these sites carry a single series. Add a series by its address, or ask the site alone with `memanga search --source DOMAIN`. |
| Not searched (shutdown) | The site shows a shutdown page. |
| Not searched (unreachable) | The domain doesn't resolve, fails TLS, or every request times out. |
| Not searched (replaced) | The domain now forwards to an unrelated site. |
| Not searched (unreliable) | Replaced, regionally blocked, or chronically timing out. |
| Not searched (region-blocked) | Blocked on some networks, where requests stall; it may work elsewhere. |
| Not searched (needs-js) | Search runs client-side; the plain HTML returns no results. |
| Not searched (challenge) | An interactive Cloudflare challenge blocks plain requests. |
| Not searched (alias) | A retired or redirecting domain of a source that is searched under its current domain. |

## Sources included in search

140 sources that a search can ask, in search order.

| Source | Other domains | Engine | Language | Adult | Search | Parser tests | Live probe | Notes |
|---|---|---|---|---|---|---|---|---|
| mangadex.org | api.mangadex.org | api | en | — | Included in search | Search, chapters, pages | Search, chapters, pages, image | Fan-translation library |
| mangapill.com | — | http | — | — | Included in search | Search, chapters, pages | Search, chapters, pages, image | General library |
| mangapark.cc | — | http | en | — | Included in search | Search, chapters, pages | Search, chapters, pages, image | General library |
| mangafire.to | — | http | — | — | Included in search | Search, chapters, pages | Search, chapters, pages, image | General library |
| mangabuddy.com | — | browser | — | — | Included in search | Search, chapters, pages | — | General library |
| weebcentral.com | — | browser | — | — | Included in search | Search, chapters, pages | Search, chapters, pages, image | General library |
| mangakatana.com | — | browser | — | — | Included in search | — | — | General library |
| asurascans.com | asuracomic.net (not searched: alias, [issue 177](https://github.com/meellm/MeManga/issues/177)), asuratoon.com (not searched: alias, [issue 177](https://github.com/meellm/MeManga/issues/177)) | api | — | — | Included in search | Search, chapters, pages | Search, chapters, pages, image | Manhwa specialist |
| comix.to | — | browser | — | — | Included in search | Search, chapters, pages | Search, chapters, pages, image | General library |
| comick.io | comick.dev | api | — | — | Included in search | Search, chapters, pages | Search, chapters | General library |
| mangahub.io | — | browser | — | — | Included in search | Chapters, pages | Search, chapters, pages, image | MangaHub network |
| mangahere.cc | — | http | — | — | Included in search | Chapters, pages | Search, chapters, pages, image | General library |
| mangapanda.onl | — | browser | — | — | Included in search | Chapters, pages | — | MangaHub network |
| mangahere.onl | — | browser | — | — | Included in search | Search, chapters | — | Alternate mirror |
| mangataro.org | — | http | — | — | Included in search | Search, chapters, pages | Search, chapters, pages, image | ComicK replacement |
| luminousscans.com | — | http | — | — | Included in search | — | — | Manhwa translations |
| tcbonepiecechapters.com | tcbscans.com, tcbscans.me | http | en | — | Included in search | Search, chapters, pages | Search, chapters, pages, image | Jump manga (One Piece, JJK) |
| fanfox.net | mangafox.me | browser | — | — | Included in search | — | — | — |
| 1manga.co | — | browser | — | — | Included in search | Chapters, pages | — | MangaHub network |
| coffeemanga.io | — | http | — | — | Included in search | — | — | — |
| manhuaplus.org | — | http | — | — | Included in search | — | — | Manhua focused |
| mangaeffect.com | — | http | — | — | Included in search | — | — | — |
| mangafox.fun | — | browser | — | — | Included in search | Shared parser: chapters, pages | — | MangaHub network |
| 1piecemanga.com | w064.1piecemanga.com | http | — | — | Included in search | Pages | — | One Piece |
| anime-sama.to | — | http | fr | — | Included in search | Search, chapters, pages | — | Unofficial French manga scans |
| atsu.moe | — | api | — | — | Included in search | Search, chapters, pages | Search, chapters, pages, image | — |
| bakirahen.com | — | http | — | — | Included in search | — | — | Baki Rahen |
| beastarsmanga.com | — | http | — | — | Included in search | Chapters, pages | — | Beastars |
| berserkmang.org | — | http | — | — | Included in search | — | — | Berserk |
| blame-manga.com | w9.blame-manga.com | http | — | — | Included in search | Pages | — | BLAME! |
| blueexorcistmanga.com | — | http | — | — | Included in search | Chapters, pages | — | Blue Exorcist |
| bluelock-read.com | — | http | — | — | Included in search | — | — | Blue Lock |
| bluelockmanga.net | — | http | — | — | Included in search | Chapters | — | Blue Lock |
| bluelockread.com | ww2.bluelockread.com | http | — | — | Included in search | — | — | Blue Lock |
| bluelockread.online | — | http | — | — | Included in search | Pages; shared parser: chapters | — | Blue Lock |
| bluesolo.org | — | api | fr | Yes | Included in search | — | — | Unofficial French scanlations from several teams |
| bocchitherockmanga.com | w5.bocchitherockmanga.com | http | — | — | Included in search | Chapters; shared parser: pages | — | Bocchi the Rock! |
| chaostrad.fr | — | http | fr | — | Included in search | Search, chapters, pages | — | French fan translation; only the Shadow the Hedgehog manga is read |
| comic-walker.com | — | http | ja | — | Included in search | Search, chapters, pages | — | Official KADOKAWA Japanese manga; public page-listed active episodes |
| death-note-manga.com | w13.death-note-manga.com | http | — | — | Included in search | Pages | — | Death Note |
| demonicscans.org | — | http | en | — | Included in search | Search, chapters, pages | — | Unofficial English manga and manhwa scans |
| demonslayermanga.com | ww9.demonslayermanga.com | http | — | — | Included in search | — | — | Demon Slayer |
| dynasty-scans.com | — | api | en | Yes | Included in search | Search, chapters, pages | — | Unofficial English yuri scanlations; explicit titles refused |
| e-hentai.org | exhentai.org | http | — | Yes | Included in search | — | — | Galleries |
| elusive-samurai.com | w4.elusive-samurai.com | http | — | — | Included in search | Shared parser: chapters, pages | — | The Elusive Samurai |
| en-thunderscans.com | — | http | en | — | Included in search | Search, chapters, pages | Search, chapters, pages, image | English manhwa scans |
| fairytailmangafree.com | — | http | — | — | Included in search | Pages | — | Fairy Tail: 100 Years Quest |
| fireforcemanga.org | w1.fireforcemanga.org | http | — | — | Included in search | Pages | — | Fire Force |
| fmteam.fr | — | api | fr | — | Included in search | — | — | Unofficial French scanlation team |
| furyosociety.com | — | http | fr | Yes | Included in search | — | — | Unofficial French scans of furyo and street manga |
| hajime-no-ippo-manga.online | — | http | — | — | Included in search | Shared parser: chapters, pages | — | Hajime no Ippo |
| hajime-noippo.com | w22.hajime-noippo.com | http | — | — | Included in search | Shared parser: chapters, pages | — | Hajime no Ippo |
| hajimnoippo.com | — | http | — | — | Included in search | Chapters, pages | — | Hajime no Ippo |
| heavenmanga.com | — | http | es | — | Included in search | Search, chapters, pages | — | Spanish manhwa, manga and manhua library |
| hentai20.io | — | http | — | Yes | Included in search | — | — | Adult content |
| hentaifox.com | — | http | — | Yes | Included in search | — | — | Doujinshi |
| hentairead.com | — | browser | — | Yes | Included in search | — | — | Doujinshi |
| homunculusmanga.com | — | http | — | — | Included in search | Chapters | — | Homunculus |
| imhentai.xxx | — | http | — | Yes | Included in search | — | — | Doujinshi |
| inventariooculto.com | — | http | — | Yes | Included in search | Search, chapters, pages | — | Manga scans; adult titles refused |
| jojolionmanga.com | — | http | — | — | Included in search | — | — | JoJo Part 8: JoJolion |
| kaijuno8-manga.com | — | http | — | — | Included in search | Pages | — | Kaiju No. 8 |
| kenganashura.com | — | http | — | — | Included in search | — | — | Kengan Ashura / Omega |
| lector-mangas.lat | lectormangass.net (not searched: alias, [issue 186](https://github.com/meellm/MeManga/issues/186)) | http | es | — | Included in search | Search, chapters, pages | Search, chapters, pages, image | Spanish manga/manhwa reader |
| leercapitulo.co | — | http | es | — | Included in search | Search, chapters, pages | — | Spanish manga/manhwa/manhua reader |
| legionscans.com | — | http | es | — | Included in search | — | — | Spanish manga, manhwa and manhua scans |
| lelmanga.com | — | http | fr | — | Included in search | Search, chapters, pages | — | French manga and manhwa scans |
| lelscanfr.com | — | http | fr | Yes | Included in search | Search, chapters, pages | — | Unofficial French manga scans; long chapter lists read from page 1 only |
| mangaball.net | — | http | — | — | Included in search | Search, chapters, pages | — | Multi-language |
| mangadenizi.net | — | http | tr | — | Included in search | Search, chapters, pages | — | Turkish manga/manhwa/webtoon reader |
| mangadna.com | — | http | — | — | Included in search | — | — | — |
| mangadot.net | — | http | — | — | Included in search | Search, chapters, pages | — | Multi-language aggregator |
| mangahome.com | — | http | en | Yes | Included in search | Search, chapters, pages | — | English manga reader |
| mangaraw.ink | — | http | — | — | Included in search | Search, chapters, pages | — | Raw manga (One Piece verified Japanese) |
| mangarw.com | — | api | — | Yes | Included in search | Search, chapters, pages | — | Raw manga (One Piece verified Japanese) |
| mangas-origines.fr | — | http | fr | — | Included in search | Search, chapters, pages | — | Unofficial French manga, manhwa and manhua scans |
| mangavault.lat | — | http | es | Yes | Included in search | Search, chapters, pages | — | Spanish manhwa, manga and manhua library |
| mangavyvy.net | vymanga.net, vyvymanga.net | http | — | — | Included in search | Search, chapters, pages | — | — |
| mangoasis.com | — | http | — | — | Included in search | — | — | — |
| manhuatop.org | — | api | en | — | Included in search | Search, chapters, pages | — | English manhua reader |
| manhwaweb.com | — | api | es | — | Included in search | Search, chapters, pages | — | Spanish manhwa, manga and manhua library |
| manytoon.com | — | browser | — | Yes | Included in search | — | — | Adult manhwa |
| mashle-manga.online | — | http | — | — | Included in search | — | — | Mashle |
| mgeko.cc | — | http | — | — | Included in search | — | Search, chapters, pages, image | — |
| monster-manga.online | — | http | — | — | Included in search | — | — | — |
| monstermanga.org | — | http | — | — | Included in search | Chapters; shared parser: pages | — | Monster |
| nhentai.net | — | http | — | Yes | Included in search | — | — | Doujinshi |
| noranofansub.com | — | http | es | Yes | Included in search | Search, chapters, pages | — | Spanish manga scans; adult titles refused |
| olympusxyz.com | — | http | es | — | Included in search | Search, chapters, pages | Search, chapters, pages, image | Spanish manhwa scans (Olympus Scanlation) |
| omegascans.org | — | browser | — | — | Included in search | — | — | Manhwa translations |
| one-punch.online | read.one-punch.online | http | — | — | Included in search | — | — | One Punch Man |
| onepiece.tube | — | http | de | — | Included in search | Search, chapters, pages | — | German One Piece main chapter list; available entries only |
| onepieceread.com | — | http | — | — | Included in search | — | — | One Piece |
| onepunchmanmangaa.com | — | http | — | — | Included in search | — | — | One Punch Man |
| onepunchmanread.com | — | http | — | — | Included in search | — | — | One Punch Man |
| patimanga.com | — | http | tr | — | Included in search | Search, chapters, pages | — | Turkish manhwa and webtoon library |
| punkrecordz.com | — | api | — | Yes | Included in search | — | — | Unofficial manga scans; series language not labelled |
| ragnarokscanlation.org | — | http | — | — | Included in search | Search, chapters, pages | — | Manga scans |
| rakuentranslations.com | — | http | es | Yes | Included in search | Search, chapters, pages | — | Spanish manga scans; adult titles refused |
| rawkuma.net | — | http | — | Yes | Included in search | Search, chapters, pages | — | Raw manga (One Piece verified Japanese) |
| rawuwu.net | — | api | — | Yes | Included in search | Search, chapters, pages | — | Raw manga (One Piece verified Japanese) |
| read-berserk-manga.com | — | http | — | — | Included in search | — | — | Berserk |
| read-jjk.com | — | http | — | — | Included in search | — | — | Jujutsu Kaisen |
| read-kengan-ashura.com | — | http | — | — | Included in search | Chapters | — | Kengan Ashura |
| read-slamdunk.online | — | http | — | — | Included in search | Chapters, pages | — | Slam Dunk |
| read-tokyorevengers.com | w20.read-tokyorevengers.com, w23.read-tokyorevengers.com | http | — | — | Included in search | Chapters, pages | — | Tokyo Revengers |
| readberserk.com | — | http | — | — | Included in search | Shared parser: search, chapters, pages | — | Berserk |
| readblackclover.com | ww7.readblackclover.com | http | — | — | Included in search | Chapters, pages | Search, chapters, pages, image | Black Clover |
| readchainsawman.com | — | http | — | — | Included in search | Shared parser: search, chapters, pages | — | Chainsaw Man |
| readcomiconline.li | — | http | — | — | Included in search | — | — | Western comics |
| readfairytail.com | ww7.readfairytail.com | http | — | — | Included in search | Shared parser: search, chapters, pages | — | Fairy Tail |
| readhaikyuu.com | — | http | — | — | Included in search | Shared parser: search, chapters, pages | — | Haikyuu!! |
| readichithewitch.com | ww1.readichithewitch.com | http | — | — | Included in search | Chapters; shared parser: pages | — | Ichi the Witch |
| readjujutsukaisen.com | — | http | — | — | Included in search | Shared parser: search, chapters, pages | — | Jujutsu Kaisen |
| readjujutsukaisenmanga.com | — | http | — | — | Included in search | — | — | Jujutsu Kaisen + Modulo |
| readkingdomfree.com | — | http | — | — | Included in search | — | — | Kingdom |
| readmha.com | ww8.readmha.com, ww10.readmha.com | http | — | — | Included in search | Shared parser: search, chapters, pages | — | My Hero Academia |
| readnaruto.com | ww8.readnaruto.com, ww10.readnaruto.com, ww11.readnaruto.com | http | — | — | Included in search | Shared parser: search, chapters, pages | — | Naruto |
| readonepiece.com | ww8.readonepiece.com, ww12.readonepiece.com | http | — | — | Included in search | Shared parser: search, chapters, pages | — | One Piece |
| readopm.com | ww6.readopm.com | http | — | — | Included in search | — | — | One Punch Man |
| readoshinoko.com | w13.readoshinoko.com | http | — | — | Included in search | — | — | Oshi no Ko |
| readsnk.com | — | http | — | — | Included in search | Shared parser: search, chapters, pages | Search | Attack on Titan |
| readsnkmanga.com | — | http | — | — | Included in search | — | — | Attack on Titan |
| sakamotomanga.com | — | http | — | — | Included in search | — | — | Sakamoto Days |
| sereinscan.com | — | http | tr | — | Included in search | Search, chapters, pages | — | Turkish manhwa reader |
| sousou-no-frieren.com | — | http | — | — | Included in search | Chapters; shared parser: pages | — | Frieren |
| spyxfamilymanga.org | — | http | — | — | Included in search | Chapters | — | Spy x Family |
| sushiscan.net | — | http | fr | — | Included in search | Search, chapters, pages | — | French manga scans |
| tgmanga.com | — | http | — | — | Included in search | Pages | — | Tokyo Ghoul |
| thedragonballsuper.online | — | http | — | — | Included in search | Chapters | — | Dragon Ball Super |
| tokyoghoul.club | — | http | — | — | Included in search | — | — | Tokyo Ghoul |
| toonily.me | — | browser | — | — | Included in search | — | — | Manhwa focused |
| uchuujinmangas.com | — | http | es | — | Included in search | Search, chapters, pages | — | Spanish manga and manhwa reader |
| uzaymanga.com | — | api | tr | — | Included in search | Search, chapters, pages | — | Turkish manga/manhwa/manhua reader |
| vagabondmanga.org | — | http | — | — | Included in search | Chapters | — | Vagabond |
| webtoons.com | — | http | — | — | Included in search | Search, chapters, pages | — | Official WEBTOON Originals in English, Spanish, French and German |
| wurmz.net | — | http | id | — | Included in search | Search, chapters, pages | Search, chapters, pages, image | Indonesian manga/manhwa/manhua reader |
| yuri-online.com | — | http | es | Yes | Included in search | Search, chapters, pages | — | Spanish yuri manga scans; adult titles refused |
| zazamanga.com | deathnotemanga.com, death-note-online.com, fairytail100yearsquest.com, gintama.site, initialdmanga.com, inuyasha.net, onepunchmanmanga.org, readhellsing.com, readoverlord.com | browser | — | — | Included in search | — | — | Also serves several redirected series sites |
| zonatmo.org | — | browser | es | — | Included in search | Search, chapters, pages | Search, chapters, pages, image | Spanish manga/manhwa library |

## Sources left out of search

18 sources. Series you already follow from them are still checked, and you can add a series by its address.

| Source | Other domains | Engine | Language | Adult | Search | Parser tests | Live probe | Notes |
|---|---|---|---|---|---|---|---|---|
| bato.to | batoto.to | http | — | — | Not searched (unreliable) | — | — | Community uploads |
| flamecomics.xyz | — | browser | — | — | Not searched (needs-js) | — | — | Manhwa translations |
| hivetoons.org | hivetoon.com | browser | — | — | Not searched (needs-js) | — | — | Void Scans network |
| kagane.org | kagane.to | browser | — | — | Not searched (challenge), [issue 182](https://github.com/meellm/MeManga/issues/182) | — | — | General library |
| kunmanga.com | — | browser | — | — | Not searched (needs-js) | — | — | — |
| mangabolt.com | — | http | — | — | Not searched (needs-js) | Search, chapters, pages | — | — |
| mangafreak.ws | mangafreak.me, ww2.mangafreak.me | http | — | — | Not searched (unreliable) | — | — | — |
| mangago.me | — | http | — | — | Not searched (region-blocked), [issue 151](https://github.com/meellm/MeManga/issues/151) | — | — | Yaoi/Shoujo collection |
| mangahub.us | — | browser | — | — | Not searched (needs-js) | Search, chapters, pages | — | MangaHub network |
| manganato.gg | — | browser | — | — | Not searched (challenge) | — | — | — |
| mangapark1.com | — | browser | — | — | Not searched (challenge), [issue 172](https://github.com/meellm/MeManga/issues/172) | Search, chapters, pages | — | General library |
| mangareader.to | — | http | — | — | Not searched (unreachable) | — | — | General library |
| mangatown.com | — | http | — | — | Not searched (unreliable) | — | — | — |
| manhuafast.com | — | http | — | — | Not searched (challenge) | — | — | Manhua focused |
| manhuaus.org | — | http | — | — | Not searched (challenge) | — | — | Manhua focused |
| manhwa18.cc | — | http | — | Yes | Not searched (unreliable) | — | — | Adult manhwa |
| raw.senmanga.com | — | api | — | Yes | Not searched (unreliable) | Chapters, pages | — | Raw manga by direct series URL; not searched (One Piece verified Japanese) |
| truemanga.com | mangamonk.com | http | — | — | Not searched (needs-js) | — | — | — |

## Template sites

79 sites built on shared site templates.

| Source | Other domains | Engine | Language | Adult | Search | Parser tests | Live probe | Notes |
|---|---|---|---|---|---|---|---|---|
| akiramanga.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | Chapters, pages, image | Akira |
| ao-ashi-manga.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Ao Ashi |
| apollcomics.es | — | http | — | — | Not searched (template) | Shared parser: search, chapters, pages | — | — |
| aquareader.net | — | http | — | — | Not searched (template) | Shared parser: search, chapters, pages | — | — |
| bakidou.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Baki (All Series) |
| bananafishmanga.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Banana Fish |
| beckmanga.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Beck: Mongolian Chop Squad |
| berserk-manga.com | w3.berserk-manga.com, w4.berserk-manga.com | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Berserk |
| blackclova.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Black Clover |
| bleach-read.com | w38.bleach-read.com | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Bleach |
| blue-box-manga.online | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Blue Box |
| blue-exorcist.online | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Blue Exorcist |
| bokugents.com | — | http | — | — | Not searched (template) | Shared parser: search, chapters, pages | — | — |
| case-closed.online | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Case Closed (Detective Conan) |
| chainsawdevil.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Chainsaw Man |
| d-grayman.online | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | D.Gray-man |
| dandadanmanga.net | ww2.dandadanmanga.net, w2.dandadanmanga.net | http | — | — | Not searched (template) | Shared parser: search, chapters, pages | — | Dandadan |
| dddmanga.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | Chapters, pages, image | Dandadan |
| deathnotemangafree.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Death Note |
| detective-conan-manga.online | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Detective Conan (Case Closed) |
| detective-conan.online | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Detective Conan |
| dorohedoro.online | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Dorohedoro |
| dragontranslation.org | — | http | — | — | Not searched (template) | Shared parser: search, chapters, pages | — | — |
| frieren-manga.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Frieren: Beyond Journey's End |
| full-metal-alchemist.online | w9.full-metal-alchemist.online | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Fullmetal Alchemist |
| gachiakutayo.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Gachiakuta |
| gantzmangafree.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Gantz |
| goblin-slayer-manga.online | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Goblin Slayer |
| gutsberserk.com | — | http | — | — | Not searched (template) | Shared parser: search, chapters, pages | — | Berserk |
| heavenly-delusion.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Tengoku Daimakyou (Heavenly Delusion) |
| hiperdex.com | — | http | — | — | Not searched (template), [issue 180](https://github.com/meellm/MeManga/issues/180) | Shared parser: search, chapters, pages | — | — |
| hxhmanga.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | Chapters, pages, image | Hunter x Hunter |
| hyoukamanga.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Hyouka |
| jjkaisen.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Jujutsu Kaisen |
| jojolandsmanga.com | w9.jojolandsmanga.com | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | JoJo's Bizarre Adventure Part 9: The JOJOLands |
| jujutsukaisenmodulo.org | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Jujutsu Kaisen Modulo |
| kagurabachi-manga.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Kagurabachi |
| kagurabachiread.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Kagurabachi |
| kaijimanga.com | w9.kaijimanga.com | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Kaiji |
| kimetsu-yaiba.online | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Demon Slayer: Kimetsu no Yaiba |
| kokounohito.com | — | http | — | — | Not searched (template) | Chapters, pages | — | The Climber (Kokou no Hito) |
| madeabyss.com | — | http | — | — | Not searched (template) | Chapters, pages | — | Made in Abyss |
| manga18fx.com | — | http | — | Yes | Not searched (template) | Shared parser: search, chapters, pages | — | Adult manga |
| mangadistrict.com | — | http | — | — | Not searched (template) | Shared parser: search, chapters, pages | — | — |
| mangaforfree.net | — | http | — | — | Not searched (template) | Shared parser: search, chapters, pages | — | — |
| mangaread.org | — | http | — | — | Not searched (template) | Shared parser: search, chapters, pages | Search, chapters, pages, image | — |
| mangawow.com | — | http | — | — | Not searched (template) | Shared parser: search, chapters, pages | — | — |
| mangazin.org | — | http | — | — | Not searched (template) | Shared parser: search, chapters, pages | — | — |
| manhwatop.com | — | http | — | — | Not searched (template) | Shared parser: search, chapters, pages | — | Manhwa focused |
| mashlemanga.net | — | http | — | — | Not searched (template) | Shared parser: search, chapters, pages | — | Mashle: Magic and Muscles |
| mushoku-tensei-manga.online | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Mushoku Tensei: Isekai Ittara Honki Dasu |
| nanamanga.online | w2.nanamanga.online | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Nana |
| onepiece-manga-online.net | w57.onepiece-manga-online.net, w58.onepiece-manga-online.net | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | One Piece |
| onepunchmanofficial.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | One Punch Man |
| oshinokoyo.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Oshi no Ko |
| overlord-manga.online | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | Chapters, pages, image | Overlord |
| punpunmanga.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Goodnight Punpun (Oyasumi Punpun) |
| rawjx.net | — | http | — | — | Not searched (template) | Shared parser: search, chapters, pages | — | — |
| readblacklagoon.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Black Lagoon |
| readclaymore.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Claymore |
| readjujutsukaisenfree.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Jujutsu Kaisen |
| readundeadunluck.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Undead Unluck |
| real-manga.online | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Real |
| record-of-ragnarok-manga.com | w1.record-of-ragnarok-manga.com | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Record of Ragnarok |
| rezero-manga.online | re-zero-manga.online | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Re:ZERO -Starting Life in Another World- |
| ruyamanga2.com | — | http | — | — | Not searched (template) | Shared parser: search, chapters, pages | — | — |
| shinobiscans.com | — | http | — | — | Not searched (template) | Shared parser: search, chapters, pages | — | — |
| skip-beat-manga.online | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Skip Beat! |
| steel-ball-run.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Steel Ball Run |
| stone-ocean-manga.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | JoJo's Bizarre Adventure Part 6: Stone Ocean |
| sxfmanga.net | ww2.sxfmanga.net | http | — | — | Not searched (template) | Shared parser: search, chapters, pages | — | Spy x Family |
| tomie-manga.com | w12.tomie-manga.com | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Tomie |
| tortugaceviri.com | — | http | — | — | Not searched (template) | Shared parser: search, chapters, pages | — | — |
| trigunmanga.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Trigun |
| unopiece.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | One Piece |
| vermanhwa.com | — | http | — | — | Not searched (template) | Shared parser: search, chapters, pages | — | — |
| witch-hat-atelier.online | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Witch Hat Atelier (Tongari Boushi no Atelier) |
| witch-watch.com | — | http | — | — | Not searched (template) | Shared parser: chapters, pages | — | Witch Watch |
| yakshascans.com | — | http | — | — | Not searched (template) | Shared parser: search, chapters, pages | — | — |
