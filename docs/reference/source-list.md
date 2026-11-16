<!-- Written by python -m memanga.source_docs; do not edit. -->

## At a glance

| | |
|---|---|
| Sources (one scraper each) | 234 |
| Domains, with other domains of the same source | 310 |
| Included in search | 114 |
| In the default selection | 15 |
| Adult content | 10 |
| In the full weekly check | 27 |

## Adult sources

::: warning Adult content
10 sources serve adult content. They are marked **Yes** in the **Adult** column below. MeManga does not hide or filter them.

- **Desktop app:** the default selection includes none of them. The **Sources** page does not mark adult sources, so check this list before you turn a source on.
- **Command line:** until the desktop app has set [`sources.disabled`](./config#sources-disabled), `memanga search` asks every source that is included in search, and that includes `e-hentai.org`, `hentai20.io`, `hentaifox.com`, `hentairead.com`, `imhentai.xxx`, `manytoon.com`, `nhentai.net`, `pururin.to`. Use `memanga search --source DOMAIN` to ask one source only.
:::

## Default selection

The first time the desktop app starts, it turns on these 15 sources and turns off the others, apart from template sites. They are searched in this order, and results from earlier sources are listed first.

| Source | Notes |
|---|---|
| mangadex.org | Fan-translation library |
| mangapill.com | General library |
| mangapark1.com | General library |
| mangafire.to | General library |
| mangabuddy.com | General library |
| weebcentral.com | General library |
| mangakatana.com | General library |
| asurascans.com | Manhwa specialist |
| comix.to | General library |
| comick.io | General library |
| mangahub.io | MangaHub network |
| mangahere.cc | General library |
| mangapanda.onl | MangaHub network |
| mangahere.onl | Alternate mirror |
| mangataro.org | ComicK replacement |

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

114 sources, in search order.

| Source | Other domains | Engine | Language | Adult | Search | Full check | Notes |
|---|---|---|---|---|---|---|---|
| mangadex.org | api.mangadex.org | api | en | — | Included in search | Yes | Fan-translation library |
| mangapill.com | — | http | — | — | Included in search | Yes | General library |
| mangapark1.com | — | browser | — | — | Included in search | Yes | General library |
| mangafire.to | — | browser | — | — | Included in search | Yes | General library |
| mangabuddy.com | — | browser | — | — | Included in search | — | General library |
| weebcentral.com | — | browser | — | — | Included in search | Yes | General library |
| mangakatana.com | — | browser | — | — | Included in search | — | General library |
| asurascans.com | asuracomic.net (not searched: alias, [issue 177](https://github.com/meellm/MeManga/issues/177)), asuratoon.com (not searched: alias, [issue 177](https://github.com/meellm/MeManga/issues/177)) | api | — | — | Included in search | Yes | Manhwa specialist |
| comix.to | — | browser | — | — | Included in search | Yes | General library |
| comick.io | comick.dev | api | — | — | Included in search | Yes | General library |
| mangahub.io | — | http | — | — | Included in search | Yes | MangaHub network |
| mangahere.cc | — | http | — | — | Included in search | Yes | General library |
| mangapanda.onl | — | http | — | — | Included in search | — | MangaHub network |
| mangahere.onl | — | browser | — | — | Included in search | — | Alternate mirror |
| mangataro.org | — | http | — | — | Included in search | Yes | ComicK replacement |
| luminousscans.com | — | http | — | — | Included in search | — | Manhwa translations |
| tcbonepiecechapters.com | tcbscans.com, tcbscans.me | http | en | — | Included in search | Yes | Jump manga (One Piece, JJK) |
| fanfox.net | mangafox.me | browser | — | — | Included in search | — | — |
| 1manga.co | — | http | — | — | Included in search | — | MangaHub network |
| coffeemanga.io | — | http | — | — | Included in search | — | — |
| manhuaplus.org | — | http | — | — | Included in search | — | Manhua focused |
| mangaeffect.com | — | http | — | — | Included in search | — | — |
| mangafox.fun | — | http | — | — | Included in search | — | MangaHub network |
| mangayy.org | likemanga.io | browser | — | — | Included in search | — | — |
| 1piecemanga.com | w064.1piecemanga.com | http | — | — | Included in search | — | One Piece |
| ajimenoippo.com | — | http | — | — | Included in search | — | Hajime no Ippo |
| atsu.moe | — | api | — | — | Included in search | Yes | — |
| bakirahen.com | — | http | — | — | Included in search | — | Baki Rahen |
| beastarsmanga.com | — | http | — | — | Included in search | — | Beastars |
| berserkmang.org | — | http | — | — | Included in search | — | Berserk |
| blame-manga.com | w9.blame-manga.com | http | — | — | Included in search | — | BLAME! |
| blueexorcistmanga.com | — | http | — | — | Included in search | — | Blue Exorcist |
| bluelock-read.com | — | http | — | — | Included in search | — | Blue Lock |
| bluelockmanga.net | — | http | — | — | Included in search | — | Blue Lock |
| bluelockread.com | ww2.bluelockread.com | http | — | — | Included in search | — | Blue Lock |
| bluelockread.online | — | http | — | — | Included in search | — | Blue Lock |
| bocchitherockmanga.com | w5.bocchitherockmanga.com | http | — | — | Included in search | — | Bocchi the Rock! |
| death-note-manga.com | w13.death-note-manga.com | http | — | — | Included in search | — | Death Note |
| demon-slayer.online | w4.demon-slayer.online | http | — | — | Included in search | — | Demon Slayer |
| demonslayermanga.com | ww9.demonslayermanga.com | http | — | — | Included in search | — | Demon Slayer |
| dragonballsuper.org | — | http | — | — | Included in search | — | Dragon Ball Super |
| drstonemanga.com | — | http | — | — | Included in search | — | Dr. Stone |
| e-hentai.org | exhentai.org | http | — | Yes | Included in search | — | Galleries |
| elusive-samurai.com | w4.elusive-samurai.com | http | — | — | Included in search | — | The Elusive Samurai |
| en-thunderscans.com | — | http | en | — | Included in search | Yes | English manhwa scans |
| fairytailmangafree.com | — | http | — | — | Included in search | — | Fairy Tail: 100 Years Quest |
| fireforcemanga.org | w1.fireforcemanga.org | http | — | — | Included in search | — | Fire Force |
| hajime-no-ippo-manga.online | — | http | — | — | Included in search | — | Hajime no Ippo |
| hajime-noippo.com | w22.hajime-noippo.com | http | — | — | Included in search | — | Hajime no Ippo |
| hajimnoippo.com | — | http | — | — | Included in search | — | Hajime no Ippo |
| hentai20.io | — | http | — | Yes | Included in search | — | Adult content |
| hentaifox.com | — | http | — | Yes | Included in search | — | Doujinshi |
| hentairead.com | — | browser | — | Yes | Included in search | — | Doujinshi |
| homunculusmanga.com | — | http | — | — | Included in search | — | Homunculus |
| imhentai.xxx | — | http | — | Yes | Included in search | — | Doujinshi |
| jjkmanga.net | — | http | — | — | Included in search | — | Jujutsu Kaisen |
| jojolionmanga.com | — | http | — | — | Included in search | — | JoJo Part 8: JoJolion |
| kaijuno8-manga.com | — | http | — | — | Included in search | — | Kaiju No. 8 |
| kenganashura.com | — | http | — | — | Included in search | — | Kengan Ashura / Omega |
| lector-mangas.lat | lectormangass.net (not searched: alias, [issue 186](https://github.com/meellm/MeManga/issues/186)) | http | es | — | Included in search | Yes | Spanish manga/manhwa reader |
| mangaball.net | — | http | — | — | Included in search | — | Multi-language |
| mangadna.com | — | http | — | — | Included in search | — | — |
| mangadot.net | — | http | — | — | Included in search | — | Multi-language aggregator |
| mangavyvy.net | vymanga.net, vyvymanga.net | http | — | — | Included in search | — | — |
| mangoasis.com | — | http | — | — | Included in search | — | — |
| manytoon.com | — | browser | — | Yes | Included in search | — | Adult manhwa |
| mashle-manga.online | — | http | — | — | Included in search | — | Mashle |
| mgeko.cc | — | http | — | — | Included in search | Yes | — |
| monster-manga.online | — | http | — | — | Included in search | — | — |
| monstermanga.org | — | http | — | — | Included in search | — | Monster |
| nhentai.net | — | http | — | Yes | Included in search | — | Doujinshi |
| olympusxyz.com | — | http | es | — | Included in search | Yes | Spanish manhwa scans (Olympus Scanlation) |
| omegascans.org | — | browser | — | — | Included in search | — | Manhwa translations |
| one-punch.online | read.one-punch.online | http | — | — | Included in search | — | One Punch Man |
| onepieceread.com | — | http | — | — | Included in search | — | One Piece |
| onepunchmanmangaa.com | — | http | — | — | Included in search | — | One Punch Man |
| onepunchmanread.com | — | http | — | — | Included in search | — | One Punch Man |
| oyasumipunpun.com | — | http | — | — | Included in search | — | Goodnight Punpun |
| pururin.to | — | browser | — | Yes | Included in search | — | Doujinshi |
| read-berserk-manga.com | — | http | — | — | Included in search | — | Berserk |
| read-jjk.com | — | http | — | — | Included in search | — | Jujutsu Kaisen |
| read-kengan-ashura.com | — | http | — | — | Included in search | — | Kengan Ashura |
| read-slamdunk.online | — | http | — | — | Included in search | — | Slam Dunk |
| read-tokyorevengers.com | w20.read-tokyorevengers.com, w23.read-tokyorevengers.com | http | — | — | Included in search | — | Tokyo Revengers |
| readberserk.com | — | http | — | — | Included in search | — | Berserk |
| readblackclover.com | ww7.readblackclover.com | http | — | — | Included in search | — | Black Clover |
| readbluelock.org | — | http | — | — | Included in search | — | Blue Lock |
| readchainsawman.com | — | http | — | — | Included in search | — | Chainsaw Man |
| readcomiconline.li | — | http | — | — | Included in search | — | Western comics |
| readfairytail.com | ww7.readfairytail.com | http | — | — | Included in search | — | Fairy Tail |
| readhaikyuu.com | — | http | — | — | Included in search | — | Haikyuu!! |
| readichithewitch.com | ww1.readichithewitch.com | http | — | — | Included in search | — | Ichi the Witch |
| readjujutsukaisen.com | — | http | — | — | Included in search | — | Jujutsu Kaisen |
| readjujutsukaisenmanga.com | — | http | — | — | Included in search | — | Jujutsu Kaisen + Modulo |
| readkingdomfree.com | — | http | — | — | Included in search | — | Kingdom |
| readmha.com | ww8.readmha.com, ww10.readmha.com | http | — | — | Included in search | — | My Hero Academia |
| readnaruto.com | ww8.readnaruto.com, ww10.readnaruto.com, ww11.readnaruto.com | http | — | — | Included in search | — | Naruto |
| readonepiece.com | ww8.readonepiece.com, ww12.readonepiece.com | http | — | — | Included in search | — | One Piece |
| readopm.com | ww6.readopm.com | http | — | — | Included in search | — | One Punch Man |
| readoshinoko.com | w13.readoshinoko.com | http | — | — | Included in search | — | Oshi no Ko |
| readsnk.com | — | http | — | — | Included in search | Yes | Attack on Titan |
| readsnkmanga.com | — | http | — | — | Included in search | — | Attack on Titan |
| sakamoto-days.online | — | http | — | — | Included in search | — | Sakamoto Days |
| sakamotomanga.com | — | http | — | — | Included in search | — | Sakamoto Days |
| sousou-no-frieren.com | — | http | — | — | Included in search | — | Frieren |
| spyxfamilymanga.org | — | http | — | — | Included in search | — | Spy x Family |
| tgmanga.com | — | http | — | — | Included in search | — | Tokyo Ghoul |
| thedragonballsuper.online | — | http | — | — | Included in search | — | Dragon Ball Super |
| tokyoghoul.club | — | http | — | — | Included in search | — | Tokyo Ghoul |
| toonily.me | — | browser | — | — | Included in search | — | Manhwa focused |
| vagabondmanga.org | — | http | — | — | Included in search | — | Vagabond |
| wurmz.net | — | http | id | — | Included in search | Yes | Indonesian manga/manhwa/manhua reader |
| zazamanga.com | deathnotemanga.com, death-note-online.com, fairytail100yearsquest.com, gintama.site, initialdmanga.com, inuyasha.net, onepunchmanmanga.org, readhellsing.com, readoverlord.com | browser | — | — | Included in search | — | Also serves several redirected series sites |
| zonatmo.org | — | http | es | — | Included in search | Yes | Spanish manga/manhwa library |

## Sources left out of search

23 sources. Series you already follow from them are still checked, and you can add a series by its address.

| Source | Other domains | Engine | Language | Adult | Search | Full check | Notes |
|---|---|---|---|---|---|---|---|
| bato.to | batoto.to | http | — | — | Not searched (unreliable) | — | Community uploads |
| flamecomics.xyz | — | browser | — | — | Not searched (needs-js) | — | Manhwa translations |
| hivetoons.org | hivetoon.com | browser | — | — | Not searched (needs-js) | — | Void Scans network |
| isekaiscan.com | — | browser | — | — | Not searched (needs-js) | — | Isekai focused |
| kagane.org | kagane.to | browser | — | — | Not searched (challenge), [issue 182](https://github.com/meellm/MeManga/issues/182) | — | General library |
| kunmanga.com | — | browser | — | — | Not searched (needs-js) | — | — |
| manga4life.com | mangalife.us | browser | — | — | Not searched (unreachable) | — | — |
| mangabolt.com | — | http | — | — | Not searched (needs-js) | — | — |
| mangaclash.com | — | browser | — | — | Not searched (unreachable), [issue 179](https://github.com/meellm/MeManga/issues/179) | — | — |
| mangafreak.ws | mangafreak.me, ww2.mangafreak.me | http | — | — | Not searched (unreliable) | — | — |
| mangago.me | — | http | — | — | Not searched (region-blocked), [issue 151](https://github.com/meellm/MeManga/issues/151) | — | Yaoi/Shoujo collection |
| mangahub.us | — | http | — | — | Not searched (needs-js) | — | MangaHub network |
| mangakakalot.com | mangakakalot.to (not searched: unreachable) | http | — | — | Not searched (replaced) | Yes | — |
| manganato.com | chapmanganato.to, readmanganato.com | http | — | — | Not searched (unreachable) | Yes | — |
| manganato.gg | — | browser | — | — | Not searched (challenge) | — | — |
| mangareader.to | — | http | — | — | Not searched (unreachable) | — | General library |
| mangasee123.com | — | http | — | — | Not searched (shutdown) | — | — |
| mangatown.com | — | http | — | — | Not searched (unreliable) | — | — |
| manhuafast.com | — | http | — | — | Not searched (challenge) | — | Manhua focused |
| manhuaus.org | — | http | — | — | Not searched (challenge) | — | Manhua focused |
| manhwa18.cc | — | http | — | Yes | Not searched (unreliable) | — | Adult manhwa |
| truemanga.com | mangamonk.com | http | — | — | Not searched (needs-js) | — | — |
| zinmanga.com | — | browser | — | — | Not searched (needs-js) | — | — |

## Template sites

97 sites built on shared site templates.

| Source | Other domains | Engine | Language | Adult | Search | Full check | Notes |
|---|---|---|---|---|---|---|---|
| akiramanga.com | — | http | — | — | Not searched (template) | Yes | Akira |
| ao-ashi-manga.com | — | http | — | — | Not searched (template) | — | Ao Ashi |
| apollcomics.es | — | http | — | — | Not searched (template) | — | — |
| aquareader.net | — | http | — | — | Not searched (template) | — | — |
| azmanga.com | — | http | — | — | Not searched (template) | — | — |
| bakidou.com | — | http | — | — | Not searched (template) | — | Baki (All Series) |
| bananafishmanga.com | — | http | — | — | Not searched (template) | — | Banana Fish |
| beckmanga.com | — | http | — | — | Not searched (template) | — | Beck: Mongolian Chop Squad |
| berserk-manga.com | w3.berserk-manga.com, w4.berserk-manga.com | http | — | — | Not searched (template) | — | Berserk |
| blackclova.com | — | http | — | — | Not searched (template) | — | Black Clover |
| bleach-read.com | w38.bleach-read.com | http | — | — | Not searched (template) | — | Bleach |
| bleachmanga.org | — | http | — | — | Not searched (template) | — | Bleach |
| blue-box-manga.online | — | http | — | — | Not searched (template) | — | Blue Box |
| blue-exorcist.online | — | http | — | — | Not searched (template) | — | Blue Exorcist |
| bokugents.com | — | http | — | — | Not searched (template) | — | — |
| call-of-the-night.online | w2.call-of-the-night.online | http | — | — | Not searched (template) | — | Call of the Night (Yofukashi no Uta) |
| case-closed.online | — | http | — | — | Not searched (template) | — | Case Closed (Detective Conan) |
| centuriya.com | — | http | — | — | Not searched (template) | — | Centuria |
| chainsawdevil.com | — | http | — | — | Not searched (template) | — | Chainsaw Man |
| d-grayman.online | — | http | — | — | Not searched (template) | — | D.Gray-man |
| dandadanmanga.net | ww2.dandadanmanga.net, w2.dandadanmanga.net | http | — | — | Not searched (template) | — | Dandadan |
| dddmanga.com | — | http | — | — | Not searched (template) | Yes | Dandadan |
| deathnotemangafree.com | — | http | — | — | Not searched (template) | — | Death Note |
| detective-conan-manga.online | — | http | — | — | Not searched (template) | — | Detective Conan (Case Closed) |
| detective-conan.online | — | http | — | — | Not searched (template) | — | Detective Conan |
| dorohedoro.online | — | http | — | — | Not searched (template) | — | Dorohedoro |
| dragontranslation.org | — | http | — | — | Not searched (template) | — | — |
| frieren-manga.com | — | http | — | — | Not searched (template) | — | Frieren: Beyond Journey's End |
| full-metal-alchemist.online | w9.full-metal-alchemist.online | http | — | — | Not searched (template) | — | Fullmetal Alchemist |
| furieren.com | — | http | — | — | Not searched (template) | — | Frieren: Beyond Journey's End |
| gachiakutayo.com | — | http | — | — | Not searched (template) | — | Gachiakuta |
| galaxxias.com | — | http | — | — | Not searched (template) | — | Galaxias |
| gantzmangafree.com | — | http | — | — | Not searched (template) | — | Gantz |
| goblin-slayer-manga.online | — | http | — | — | Not searched (template) | — | Goblin Slayer |
| grandbluemanga.com | — | http | — | — | Not searched (template) | — | Grand Blue Dreaming |
| gutsberserk.com | — | http | — | — | Not searched (template) | — | Berserk |
| heavenly-delusion.com | — | http | — | — | Not searched (template) | — | Tengoku Daimakyou (Heavenly Delusion) |
| hipercool.net | — | http | — | — | Not searched (template) | — | — |
| hiperdex.com | — | http | — | — | Not searched (template), [issue 180](https://github.com/meellm/MeManga/issues/180) | — | — |
| hxhmanga.com | — | http | — | — | Not searched (template) | Yes | Hunter x Hunter |
| hyoukamanga.com | — | http | — | — | Not searched (template) | — | Hyouka |
| ichithewitchread.com | — | http | — | — | Not searched (template) | — | Ichi the Witch |
| jjkaisen.com | — | http | — | — | Not searched (template) | — | Jujutsu Kaisen |
| jojolandsmanga.com | w9.jojolandsmanga.com | http | — | — | Not searched (template) | — | JoJo's Bizarre Adventure Part 9: The JOJOLands |
| jujutsukaisenmodulo.org | — | http | — | — | Not searched (template) | — | Jujutsu Kaisen Modulo |
| jujutsumodulo.com | — | http | — | — | Not searched (template) | — | Jujutsu Kaisen Modulo |
| kagurabachi-manga.com | — | http | — | — | Not searched (template) | — | Kagurabachi |
| kagurabachiread.com | — | http | — | — | Not searched (template) | — | Kagurabachi |
| kaijimanga.com | w9.kaijimanga.com | http | — | — | Not searched (template) | — | Kaiji |
| kimetsu-yaiba.online | — | http | — | — | Not searched (template) | — | Demon Slayer: Kimetsu no Yaiba |
| kokounohito.com | — | http | — | — | Not searched (template) | — | The Climber (Kokou no Hito) |
| madeabyss.com | — | http | — | — | Not searched (template) | — | Made in Abyss |
| manga18fx.com | — | http | — | Yes | Not searched (template) | — | Adult manga |
| mangadistrict.com | — | http | — | — | Not searched (template) | — | — |
| mangaforfree.net | — | http | — | — | Not searched (template) | — | — |
| mangaread.org | — | http | — | — | Not searched (template) | Yes | — |
| mangasehri.com | — | http | — | — | Not searched (template) | — | — |
| mangawow.com | — | http | — | — | Not searched (template) | — | — |
| mangazin.org | — | http | — | — | Not searched (template) | — | — |
| manhwatop.com | — | http | — | — | Not searched (template) | — | Manhwa focused |
| mashlemanga.net | — | http | — | — | Not searched (template) | — | Mashle: Magic and Muscles |
| mushoku-tensei-manga.online | — | http | — | — | Not searched (template) | — | Mushoku Tensei: Isekai Ittara Honki Dasu |
| nanamanga.online | w2.nanamanga.online | http | — | — | Not searched (template) | — | Nana |
| onepiece-manga-online.net | w57.onepiece-manga-online.net, w58.onepiece-manga-online.net | http | — | — | Not searched (template) | — | One Piece |
| onepunchmanofficial.com | — | http | — | — | Not searched (template) | — | One Punch Man |
| oshinokoyo.com | — | http | — | — | Not searched (template) | — | Oshi no Ko |
| overlord-manga.online | — | http | — | — | Not searched (template) | Yes | Overlord |
| parasytemanga.com | w9.parasytemanga.com | http | — | — | Not searched (template) | — | Parasyte |
| pawmanga.com | — | http | — | — | Not searched (template) | — | — |
| punpunmanga.com | — | http | — | — | Not searched (template) | — | Goodnight Punpun (Oyasumi Punpun) |
| rawjx.net | — | http | — | — | Not searched (template) | — | — |
| readblacklagoon.com | — | http | — | — | Not searched (template) | — | Black Lagoon |
| readclaymore.com | — | http | — | — | Not searched (template) | — | Claymore |
| readjujutsukaisenfree.com | — | http | — | — | Not searched (template) | — | Jujutsu Kaisen |
| readundeadunluck.com | — | http | — | — | Not searched (template) | — | Undead Unluck |
| real-manga.online | — | http | — | — | Not searched (template) | — | Real |
| record-of-ragnarok-manga.com | w1.record-of-ragnarok-manga.com | http | — | — | Not searched (template) | — | Record of Ragnarok |
| reset-scans.org | — | http | — | — | Not searched (template) | — | — |
| rezero-manga.online | re-zero-manga.online | http | — | — | Not searched (template) | — | Re:ZERO -Starting Life in Another World- |
| ruyamanga2.com | — | http | — | — | Not searched (template) | — | — |
| s2manga.com | s2manga.io | http | — | — | Not searched (template) | — | — |
| shinobiscans.com | — | http | — | — | Not searched (template) | — | — |
| skip-beat-manga.online | — | http | — | — | Not searched (template) | — | Skip Beat! |
| skip-beat.online | — | http | — | — | Not searched (template) | — | Skip Beat! |
| steel-ball-run.com | — | http | — | — | Not searched (template) | — | Steel Ball Run |
| stone-ocean-manga.com | — | http | — | — | Not searched (template) | — | JoJo's Bizarre Adventure Part 6: Stone Ocean |
| sxfmanga.net | ww2.sxfmanga.net | http | — | — | Not searched (template) | — | Spy x Family |
| tomie-manga.com | w12.tomie-manga.com | http | — | — | Not searched (template) | — | Tomie |
| tortugaceviri.com | — | http | — | — | Not searched (template) | — | — |
| trigunmanga.com | — | http | — | — | Not searched (template) | — | Trigun |
| unopiece.com | — | http | — | — | Not searched (template) | — | One Piece |
| vermanhwa.com | — | http | — | — | Not searched (template) | — | — |
| vinlandsagamanga.net | ww3.vinlandsagamanga.net, w3.vinlandsagamanga.net | http | — | — | Not searched (template) | — | Vinland Saga |
| witch-hat-atelier.online | — | http | — | — | Not searched (template) | — | Witch Hat Atelier (Tongari Boushi no Atelier) |
| witch-watch.com | — | http | — | — | Not searched (template) | — | Witch Watch |
| world-trigger.online | — | http | — | — | Not searched (template) | — | World Trigger |
| yakshascans.com | — | http | — | — | Not searched (template) | — | — |
