# Supported Sources

MeManga registers 306 domains across 241 scrapers. Registration does not mean a site is currently reachable.
Search status says whether a search can ask a source, not whether it is in the default selection; direct URLs remain available for registered sources.
Use `memanga sources --json` for per-domain skip reasons and issue numbers; open those numbers in the repository issue tracker.
Live probe: the steps the weekly [scraper health check](https://github.com/meellm/MeManga/actions/workflows/scraper-health.yml) runs against this source after opening its home page, out of search, chapters (the chapter list), pages (the page list of one chapter) and image (downloading one page). Being in the probe does not mean the last run passed.
Parser tests: the parts of the scraper (search, chapters, pages) that offline tests run on saved or canned responses from the site; "shared parser" means the tests ran code this source shares with other sites, on another site's responses; a source that replaces any of that code with its own is not credited with it.
The [documentation site](https://meellm.github.io/MeManga/reference/sources) explains these columns.

| Source | Aliases | Engine | Language | NSFW | Search status | Notes | Live probe | Parser tests |
|---|---|---|---|---|---|---|---|---|
| mangadex.org | api.mangadex.org (Included in search) | api | en | No | Included in search | Fan-translation library | Search, chapters, pages, image | Search, chapters, pages |
| mangapill.com | — | http | — | No | Included in search | General library | Search, chapters, pages, image | Search, chapters, pages |
| mangapark.cc | — | http | en | No | Included in search | General library | Search, chapters, pages, image | Search, chapters, pages |
| mangafire.to | — | http | — | No | Included in search | General library | Search, chapters, pages, image | Search, chapters, pages |
| mangabuddy.com | — | browser | — | No | Included in search | General library | — | Search, chapters, pages |
| weebcentral.com | — | browser | — | No | Included in search | General library | Search, chapters, pages, image | Search, chapters, pages |
| mangakatana.com | — | browser | — | No | Included in search | General library | — | — |
| asurascans.com | asuracomic.net (Not searched (alias)), asuratoon.com (Not searched (alias)) | api | — | No | Included in search | Manhwa specialist | Search, chapters, pages, image | Search, chapters, pages |
| comix.to | — | browser | — | No | Included in search | General library | Search, chapters, pages, image | Search, chapters, pages |
| comick.io | comick.dev (Included in search) | api | — | No | Included in search | General library | Search, chapters | Search, chapters, pages |
| mangahub.io | — | browser | — | No | Included in search | MangaHub network | Search, chapters, pages, image | Chapters, pages |
| mangahere.cc | — | http | — | No | Included in search | General library | Search, chapters, pages, image | Chapters, pages |
| mangapanda.onl | — | browser | — | No | Included in search | MangaHub network | — | Chapters, pages |
| mangahere.onl | — | browser | — | No | Included in search | Alternate mirror | — | Search, chapters |
| mangataro.org | — | http | — | No | Included in search | ComicK replacement | Search, chapters, pages, image | Search, chapters, pages |
| luminousscans.com | — | http | — | No | Included in search | Manhwa translations | — | — |
| tcbonepiecechapters.com | tcbscans.com (Included in search), tcbscans.me (Included in search) | http | en | No | Included in search | Jump manga (One Piece, JJK) | Search, chapters, pages, image | Search, chapters, pages |
| fanfox.net | mangafox.me (Included in search) | browser | — | No | Included in search | — | — | — |
| 1manga.co | — | browser | — | No | Included in search | MangaHub network | — | Chapters, pages |
| coffeemanga.io | — | http | — | No | Included in search | — | — | — |
| manhuaplus.org | — | http | — | No | Included in search | Manhua focused | — | — |
| mangaeffect.com | — | http | — | No | Included in search | — | — | — |
| mangafox.fun | — | browser | — | No | Included in search | MangaHub network | — | Shared parser: chapters, pages |
| 1piecemanga.com | w064.1piecemanga.com (Included in search) | http | — | No | Included in search | One Piece | — | Pages |
| akiramanga.com | — | http | — | No | Not searched (template) | Akira | Chapters, pages, image | Shared parser: chapters, pages |
| anime-sama.to | — | http | fr | No | Included in search | Unofficial French manga scans | — | Search, chapters, pages |
| ao-ashi-manga.com | — | http | — | No | Not searched (template) | Ao Ashi | — | Shared parser: chapters, pages |
| apollcomics.es | — | http | — | No | Not searched (template) | — | — | Shared parser: search, chapters, pages |
| aquareader.net | — | http | — | No | Not searched (template) | — | — | Shared parser: search, chapters, pages |
| atsu.moe | — | api | — | No | Included in search | — | Search, chapters, pages, image | Search, chapters, pages |
| bakidou.com | — | http | — | No | Not searched (template) | Baki (All Series) | — | Shared parser: chapters, pages |
| bakirahen.com | — | http | — | No | Included in search | Baki Rahen | — | — |
| bananafishmanga.com | — | http | — | No | Not searched (template) | Banana Fish | — | Shared parser: chapters, pages |
| bato.to | batoto.to (Not searched (unreliable)) | http | — | No | Not searched (unreliable) | Community uploads | — | — |
| beastarsmanga.com | — | http | — | No | Included in search | Beastars | — | Chapters, pages |
| beckmanga.com | — | http | — | No | Not searched (template) | Beck: Mongolian Chop Squad | — | Shared parser: chapters, pages |
| berserk-manga.com | w3.berserk-manga.com (Not searched (template)), w4.berserk-manga.com (Not searched (template)) | http | — | No | Not searched (template) | Berserk | — | Shared parser: chapters, pages |
| berserkmang.org | — | http | — | No | Included in search | Berserk | — | — |
| blackclova.com | — | http | — | No | Not searched (template) | Black Clover | — | Shared parser: chapters, pages |
| blame-manga.com | w9.blame-manga.com (Included in search) | http | — | No | Included in search | BLAME! | — | Pages |
| bleach-read.com | w38.bleach-read.com (Not searched (template)) | http | — | No | Not searched (template) | Bleach | — | Shared parser: chapters, pages |
| blue-box-manga.online | — | http | — | No | Not searched (template) | Blue Box | — | Shared parser: chapters, pages |
| blue-exorcist.online | — | http | — | No | Not searched (template) | Blue Exorcist | — | Shared parser: chapters, pages |
| blueexorcistmanga.com | — | http | — | No | Included in search | Blue Exorcist | — | Chapters, pages |
| bluelock-read.com | — | http | — | No | Included in search | Blue Lock | — | — |
| bluelockmanga.net | — | http | — | No | Included in search | Blue Lock | — | Chapters |
| bluelockread.com | ww2.bluelockread.com (Included in search) | http | — | No | Included in search | Blue Lock | — | — |
| bluelockread.online | — | http | — | No | Included in search | Blue Lock | — | Pages; shared parser: chapters |
| bluesolo.org | — | api | fr | Yes | Included in search | Unofficial French scanlations from several teams | — | — |
| bocchitherockmanga.com | w5.bocchitherockmanga.com (Included in search) | http | — | No | Included in search | Bocchi the Rock! | — | Chapters; shared parser: pages |
| bokugents.com | — | http | — | No | Not searched (template) | — | — | Shared parser: search, chapters, pages |
| case-closed.online | — | http | — | No | Not searched (template) | Case Closed (Detective Conan) | — | Shared parser: chapters, pages |
| chainsawdevil.com | — | http | — | No | Not searched (template) | Chainsaw Man | — | Shared parser: chapters, pages |
| chaostrad.fr | — | http | fr | No | Included in search | French fan translation; only the Shadow the Hedgehog manga is read | — | Search, chapters, pages |
| comic-walker.com | — | http | ja | No | Included in search | Official KADOKAWA Japanese manga; public page-listed active episodes | — | Search, chapters, pages |
| d-grayman.online | — | http | — | No | Not searched (template) | D.Gray-man | — | Shared parser: chapters, pages |
| dandadanmanga.net | ww2.dandadanmanga.net (Not searched (template)), w2.dandadanmanga.net (Not searched (template)) | http | — | No | Not searched (template) | Dandadan | — | Shared parser: search, chapters, pages |
| dddmanga.com | — | http | — | No | Not searched (template) | Dandadan | Chapters, pages, image | Shared parser: chapters, pages |
| death-note-manga.com | w13.death-note-manga.com (Included in search) | http | — | No | Included in search | Death Note | — | Pages |
| deathnotemangafree.com | — | http | — | No | Not searched (template) | Death Note | — | Shared parser: chapters, pages |
| demonicscans.org | — | http | en | No | Included in search | Unofficial English manga and manhwa scans | — | Search, chapters, pages |
| demonslayermanga.com | ww9.demonslayermanga.com (Included in search) | http | — | No | Included in search | Demon Slayer | — | — |
| detective-conan-manga.online | — | http | — | No | Not searched (template) | Detective Conan (Case Closed) | — | Shared parser: chapters, pages |
| detective-conan.online | — | http | — | No | Not searched (template) | Detective Conan | — | Shared parser: chapters, pages |
| dorohedoro.online | — | http | — | No | Not searched (template) | Dorohedoro | — | Shared parser: chapters, pages |
| dragontranslation.org | — | http | — | No | Not searched (template) | — | — | Shared parser: search, chapters, pages |
| dynasty-scans.com | — | api | en | Yes | Included in search | Unofficial English yuri scanlations; explicit titles refused | — | Search, chapters, pages |
| e-hentai.org | exhentai.org (Included in search) | http | — | Yes | Included in search | Galleries | — | — |
| elusive-samurai.com | w4.elusive-samurai.com (Included in search) | http | — | No | Included in search | The Elusive Samurai | — | Shared parser: chapters, pages |
| en-thunderscans.com | — | http | en | No | Included in search | English manhwa scans | Search, chapters, pages, image | Search, chapters, pages |
| fairytailmangafree.com | — | http | — | No | Included in search | Fairy Tail: 100 Years Quest | — | Pages |
| fireforcemanga.org | w1.fireforcemanga.org (Included in search) | http | — | No | Included in search | Fire Force | — | Pages |
| flamecomics.xyz | — | browser | — | No | Not searched (needs-js) | Manhwa translations | — | — |
| fmteam.fr | — | api | fr | No | Included in search | Unofficial French scanlation team | — | — |
| frieren-manga.com | — | http | — | No | Not searched (template) | Frieren: Beyond Journey's End | — | Shared parser: chapters, pages |
| full-metal-alchemist.online | w9.full-metal-alchemist.online (Not searched (template)) | http | — | No | Not searched (template) | Fullmetal Alchemist | — | Shared parser: chapters, pages |
| furyosociety.com | — | http | fr | Yes | Included in search | Unofficial French scans of furyo and street manga | — | — |
| gachiakutayo.com | — | http | — | No | Not searched (template) | Gachiakuta | — | Shared parser: chapters, pages |
| gantzmangafree.com | — | http | — | No | Not searched (template) | Gantz | — | Shared parser: chapters, pages |
| goblin-slayer-manga.online | — | http | — | No | Not searched (template) | Goblin Slayer | — | Shared parser: chapters, pages |
| gutsberserk.com | — | http | — | No | Not searched (template) | Berserk | — | Shared parser: search, chapters, pages |
| hajime-no-ippo-manga.online | — | http | — | No | Included in search | Hajime no Ippo | — | Shared parser: chapters, pages |
| hajime-noippo.com | w22.hajime-noippo.com (Included in search) | http | — | No | Included in search | Hajime no Ippo | — | Shared parser: chapters, pages |
| hajimnoippo.com | — | http | — | No | Included in search | Hajime no Ippo | — | Chapters, pages |
| heavenly-delusion.com | — | http | — | No | Not searched (template) | Tengoku Daimakyou (Heavenly Delusion) | — | Shared parser: chapters, pages |
| heavenmanga.com | — | http | es | No | Included in search | Spanish manhwa, manga and manhua library | — | Search, chapters, pages |
| hentai20.io | — | http | — | Yes | Included in search | Adult content | — | — |
| hentaifox.com | — | http | — | Yes | Included in search | Doujinshi | — | — |
| hentairead.com | — | browser | — | Yes | Included in search | Doujinshi | — | — |
| hiperdex.com | — | http | — | No | Not searched (template) | — | — | Shared parser: search, chapters, pages |
| hivetoons.org | hivetoon.com (Not searched (needs-js)) | browser | — | No | Not searched (needs-js) | Void Scans network | — | — |
| homunculusmanga.com | — | http | — | No | Included in search | Homunculus | — | Chapters |
| hxhmanga.com | — | http | — | No | Not searched (template) | Hunter x Hunter | Chapters, pages, image | Shared parser: chapters, pages |
| hyoukamanga.com | — | http | — | No | Not searched (template) | Hyouka | — | Shared parser: chapters, pages |
| imhentai.xxx | — | http | — | Yes | Included in search | Doujinshi | — | — |
| inmanga.com | — | http | es | Yes | Included in search | Spanish manga library; adult-flagged chapters refused | — | Search, chapters, pages |
| inventariooculto.com | — | http | — | Yes | Included in search | Manga scans; adult titles refused | — | Search, chapters, pages |
| jjkaisen.com | — | http | — | No | Not searched (template) | Jujutsu Kaisen | — | Shared parser: chapters, pages |
| jojolandsmanga.com | w9.jojolandsmanga.com (Not searched (template)) | http | — | No | Not searched (template) | JoJo's Bizarre Adventure Part 9: The JOJOLands | — | Shared parser: chapters, pages |
| jojolionmanga.com | — | http | — | No | Included in search | JoJo Part 8: JoJolion | — | — |
| jujutsukaisenmodulo.org | — | http | — | No | Not searched (template) | Jujutsu Kaisen Modulo | — | Shared parser: chapters, pages |
| kagane.org | kagane.to (Not searched (challenge)) | browser | — | No | Not searched (challenge) | General library | — | — |
| kagurabachi-manga.com | — | http | — | No | Not searched (template) | Kagurabachi | — | Shared parser: chapters, pages |
| kagurabachiread.com | — | http | — | No | Not searched (template) | Kagurabachi | — | Shared parser: chapters, pages |
| kaijimanga.com | w9.kaijimanga.com (Not searched (template)) | http | — | No | Not searched (template) | Kaiji | — | Shared parser: chapters, pages |
| kaijuno8-manga.com | — | http | — | No | Included in search | Kaiju No. 8 | — | Pages |
| kenganashura.com | — | http | — | No | Included in search | Kengan Ashura / Omega | — | — |
| kimetsu-yaiba.online | — | http | — | No | Not searched (template) | Demon Slayer: Kimetsu no Yaiba | — | Shared parser: chapters, pages |
| kokounohito.com | — | http | — | No | Not searched (template) | The Climber (Kokou no Hito) | — | Chapters, pages |
| kunmanga.com | — | browser | — | No | Not searched (needs-js) | — | — | — |
| lanortrad.com | — | http | fr | No | Included in search | Unofficial French manga translations; only series the site marks readable | — | Search, chapters, pages |
| lector-mangas.lat | lectormangass.net (Not searched (alias)) | http | es | No | Included in search | Spanish manga/manhwa reader | Search, chapters, pages, image | Search, chapters, pages |
| leercapitulo.co | — | http | es | No | Included in search | Spanish manga/manhwa/manhua reader | — | Search, chapters, pages |
| legionscans.com | — | http | es | No | Included in search | Spanish manga, manhwa and manhua scans | — | — |
| lelmanga.com | — | http | fr | No | Included in search | French manga and manhwa scans | — | Search, chapters, pages |
| lelscanfr.com | — | http | fr | Yes | Included in search | Unofficial French manga scans; long chapter lists read from page 1 only | — | Search, chapters, pages |
| madeabyss.com | — | http | — | No | Not searched (template) | Made in Abyss | — | Chapters, pages |
| mahoushoujobu.com | — | api | en | Yes | Included in search | Unofficial English manga translations (Magical Translators); English series only | — | Search, chapters, pages |
| manga-corporation.com | — | api | fr | No | Included in search | Unofficial French manga translations (Manga-Corporation); numbered chapters only | — | Search, chapters, pages |
| manga18fx.com | — | http | — | Yes | Not searched (template) | Adult manga | — | Shared parser: search, chapters, pages |
| mangaball.net | — | http | — | No | Included in search | Multi-language | — | Search, chapters, pages |
| mangabolt.com | — | http | — | No | Not searched (needs-js) | — | — | Search, chapters, pages |
| mangadenizi.net | — | http | tr | No | Included in search | Turkish manga/manhwa/webtoon reader | — | Search, chapters, pages |
| mangadistrict.com | — | http | — | No | Not searched (template) | — | — | Shared parser: search, chapters, pages |
| mangadna.com | — | http | — | No | Included in search | — | — | — |
| mangadot.net | — | http | — | No | Included in search | Multi-language aggregator | — | Search, chapters, pages |
| mangaforfree.net | — | http | — | No | Not searched (template) | — | — | Shared parser: search, chapters, pages |
| mangafreak.ws | mangafreak.me (Not searched (unreliable)), ww2.mangafreak.me (Not searched (unreliable)) | http | — | No | Not searched (unreliable) | — | — | — |
| mangago.me | — | http | — | No | Not searched (region-blocked) | Yaoi/Shoujo collection | — | — |
| mangahome.com | — | http | en | Yes | Included in search | English manga reader | — | Search, chapters, pages |
| mangahub.us | — | browser | — | No | Not searched (needs-js) | MangaHub network | — | Search, chapters, pages |
| manganato.gg | — | browser | — | No | Not searched (challenge) | — | — | — |
| mangapark1.com | — | browser | — | No | Not searched (challenge) | General library | — | Search, chapters, pages |
| mangaraw.ink | — | http | — | No | Included in search | Raw manga (One Piece verified Japanese) | — | Search, chapters, pages |
| mangaread.org | — | http | — | No | Not searched (template) | — | Search, chapters, pages, image | Shared parser: search, chapters, pages |
| mangareader.to | — | http | — | No | Not searched (unreachable) | General library | — | — |
| mangarw.com | — | api | — | Yes | Included in search | Raw manga (One Piece verified Japanese) | — | Search, chapters, pages |
| mangas-origines.fr | — | http | fr | No | Included in search | Unofficial French manga, manhwa and manhua scans | — | Search, chapters, pages |
| mangatown.com | — | http | — | No | Not searched (unreliable) | — | — | — |
| mangavault.lat | — | http | es | Yes | Included in search | Spanish manhwa, manga and manhua library | — | Search, chapters, pages |
| mangavyvy.net | vymanga.net (Included in search), vyvymanga.net (Included in search) | http | — | No | Included in search | — | — | Search, chapters, pages |
| mangawow.com | — | http | — | No | Not searched (template) | — | — | Shared parser: search, chapters, pages |
| mangazin.org | — | http | — | No | Not searched (template) | — | — | Shared parser: search, chapters, pages |
| mangoasis.com | — | http | — | No | Included in search | — | — | — |
| manhuafast.com | — | http | — | No | Not searched (challenge) | Manhua focused | — | — |
| manhuatop.org | — | api | en | No | Included in search | English manhua reader | — | Search, chapters, pages |
| manhuaus.org | — | http | — | No | Not searched (challenge) | Manhua focused | — | — |
| manhwa18.cc | — | http | — | Yes | Not searched (unreliable) | Adult manhwa | — | — |
| manhwatop.com | — | http | — | No | Not searched (template) | Manhwa focused | — | Shared parser: search, chapters, pages |
| manhwaweb.com | — | api | es | No | Included in search | Spanish manhwa, manga and manhua library | — | Search, chapters, pages |
| manytoon.com | — | browser | — | Yes | Included in search | Adult manhwa | — | — |
| mashle-manga.online | — | http | — | No | Included in search | Mashle | — | — |
| mashlemanga.net | — | http | — | No | Not searched (template) | Mashle: Magic and Muscles | — | Shared parser: search, chapters, pages |
| mgeko.cc | — | http | — | No | Included in search | — | Search, chapters, pages, image | — |
| monster-manga.online | — | http | — | No | Included in search | — | — | — |
| monstermanga.org | — | http | — | No | Included in search | Monster | — | Chapters; shared parser: pages |
| mushoku-tensei-manga.online | — | http | — | No | Not searched (template) | Mushoku Tensei: Isekai Ittara Honki Dasu | — | Shared parser: chapters, pages |
| nanamanga.online | w2.nanamanga.online (Not searched (template)) | http | — | No | Not searched (template) | Nana | — | Shared parser: chapters, pages |
| nhentai.net | — | http | — | Yes | Included in search | Doujinshi | — | — |
| noranofansub.com | — | http | es | Yes | Included in search | Spanish manga scans; adult titles refused | — | Search, chapters, pages |
| olympusxyz.com | — | http | es | No | Included in search | Spanish manhwa scans (Olympus Scanlation) | Search, chapters, pages, image | Search, chapters, pages |
| omegascans.org | — | browser | — | No | Included in search | Manhwa translations | — | — |
| one-punch.online | read.one-punch.online (Included in search) | http | — | No | Included in search | One Punch Man | — | — |
| onepiece-manga-online.net | w57.onepiece-manga-online.net (Not searched (template)), w58.onepiece-manga-online.net (Not searched (template)) | http | — | No | Not searched (template) | One Piece | — | Shared parser: chapters, pages |
| onepiece.tube | — | http | de | No | Included in search | German One Piece main chapter list; available entries only | — | Search, chapters, pages |
| onepieceread.com | — | http | — | No | Included in search | One Piece | — | — |
| onepunchmanmangaa.com | — | http | — | No | Included in search | One Punch Man | — | — |
| onepunchmanofficial.com | — | http | — | No | Not searched (template) | One Punch Man | — | Shared parser: chapters, pages |
| onepunchmanread.com | — | http | — | No | Included in search | One Punch Man | — | — |
| oshinokoyo.com | — | http | — | No | Not searched (template) | Oshi no Ko | — | Shared parser: chapters, pages |
| overlord-manga.online | — | http | — | No | Not searched (template) | Overlord | Chapters, pages, image | Shared parser: chapters, pages |
| patimanga.com | — | http | tr | No | Included in search | Turkish manhwa and webtoon library | — | Search, chapters, pages |
| punkrecordz.com | — | api | — | Yes | Included in search | Unofficial manga scans; series language not labelled | — | — |
| punpunmanga.com | — | http | — | No | Not searched (template) | Goodnight Punpun (Oyasumi Punpun) | — | Shared parser: chapters, pages |
| ragnarokscanlation.org | — | http | — | No | Included in search | Manga scans | — | Search, chapters, pages |
| rakuentranslations.com | — | http | es | Yes | Included in search | Spanish manga scans; adult titles refused | — | Search, chapters, pages |
| raw.senmanga.com | — | api | — | Yes | Not searched (unreliable) | Raw manga by direct series URL; not searched (One Piece verified Japanese) | — | Chapters, pages |
| rawjx.net | — | http | — | No | Not searched (template) | — | — | Shared parser: search, chapters, pages |
| rawkuma.net | — | http | — | Yes | Included in search | Raw manga (One Piece verified Japanese) | — | Search, chapters, pages |
| rawuwu.net | — | api | — | Yes | Included in search | Raw manga (One Piece verified Japanese) | — | Search, chapters, pages |
| read-berserk-manga.com | — | http | — | No | Included in search | Berserk | — | — |
| read-jjk.com | — | http | — | No | Included in search | Jujutsu Kaisen | — | — |
| read-kengan-ashura.com | — | http | — | No | Included in search | Kengan Ashura | — | Chapters |
| read-slamdunk.online | — | http | — | No | Included in search | Slam Dunk | — | Chapters, pages |
| read-tokyorevengers.com | w20.read-tokyorevengers.com (Included in search), w23.read-tokyorevengers.com (Included in search) | http | — | No | Included in search | Tokyo Revengers | — | Chapters, pages |
| readberserk.com | — | http | — | No | Included in search | Berserk | — | Shared parser: search, chapters, pages |
| readblackclover.com | ww7.readblackclover.com (Included in search) | http | — | No | Included in search | Black Clover | Search, chapters, pages, image | Chapters, pages |
| readblacklagoon.com | — | http | — | No | Not searched (template) | Black Lagoon | — | Shared parser: chapters, pages |
| readchainsawman.com | — | http | — | No | Included in search | Chainsaw Man | — | Shared parser: search, chapters, pages |
| readclaymore.com | — | http | — | No | Not searched (template) | Claymore | — | Shared parser: chapters, pages |
| readcomiconline.li | — | http | — | No | Included in search | Western comics | — | — |
| readfairytail.com | ww7.readfairytail.com (Included in search) | http | — | No | Included in search | Fairy Tail | — | Shared parser: search, chapters, pages |
| readhaikyuu.com | — | http | — | No | Included in search | Haikyuu!! | — | Shared parser: search, chapters, pages |
| readichithewitch.com | ww1.readichithewitch.com (Included in search) | http | — | No | Included in search | Ichi the Witch | — | Chapters; shared parser: pages |
| readjujutsukaisen.com | — | http | — | No | Included in search | Jujutsu Kaisen | — | Shared parser: search, chapters, pages |
| readjujutsukaisenfree.com | — | http | — | No | Not searched (template) | Jujutsu Kaisen | — | Shared parser: chapters, pages |
| readjujutsukaisenmanga.com | — | http | — | No | Included in search | Jujutsu Kaisen + Modulo | — | — |
| readkingdomfree.com | — | http | — | No | Included in search | Kingdom | — | — |
| readmha.com | ww8.readmha.com (Included in search), ww10.readmha.com (Included in search) | http | — | No | Included in search | My Hero Academia | — | Shared parser: search, chapters, pages |
| readnaruto.com | ww8.readnaruto.com (Included in search), ww10.readnaruto.com (Included in search), ww11.readnaruto.com (Included in search) | http | — | No | Included in search | Naruto | — | Shared parser: search, chapters, pages |
| readonepiece.com | ww8.readonepiece.com (Included in search), ww12.readonepiece.com (Included in search) | http | — | No | Included in search | One Piece | — | Shared parser: search, chapters, pages |
| readopm.com | ww6.readopm.com (Included in search) | http | — | No | Included in search | One Punch Man | — | — |
| readoshinoko.com | w13.readoshinoko.com (Included in search) | http | — | No | Included in search | Oshi no Ko | — | — |
| readsnk.com | — | http | — | No | Included in search | Attack on Titan | Search | Shared parser: search, chapters, pages |
| readsnkmanga.com | — | http | — | No | Included in search | Attack on Titan | — | — |
| readundeadunluck.com | — | http | — | No | Not searched (template) | Undead Unluck | — | Shared parser: chapters, pages |
| real-manga.online | — | http | — | No | Not searched (template) | Real | — | Shared parser: chapters, pages |
| record-of-ragnarok-manga.com | w1.record-of-ragnarok-manga.com (Not searched (template)) | http | — | No | Not searched (template) | Record of Ragnarok | — | Shared parser: chapters, pages |
| rezero-manga.online | re-zero-manga.online (Not searched (template)) | http | — | No | Not searched (template) | Re:ZERO -Starting Life in Another World- | — | Shared parser: chapters, pages |
| ruyamanga2.com | — | http | — | No | Not searched (template) | — | — | Shared parser: search, chapters, pages |
| sakamotomanga.com | — | http | — | No | Included in search | Sakamoto Days | — | — |
| sereinscan.com | — | http | tr | No | Included in search | Turkish manhwa reader | — | Search, chapters, pages |
| shinobiscans.com | — | http | — | No | Not searched (template) | — | — | Shared parser: search, chapters, pages |
| skip-beat-manga.online | — | http | — | No | Not searched (template) | Skip Beat! | — | Shared parser: chapters, pages |
| sousou-no-frieren.com | — | http | — | No | Included in search | Frieren | — | Chapters; shared parser: pages |
| spyxfamilymanga.org | — | http | — | No | Included in search | Spy x Family | — | Chapters |
| steel-ball-run.com | — | http | — | No | Not searched (template) | Steel Ball Run | — | Shared parser: chapters, pages |
| stone-ocean-manga.com | — | http | — | No | Not searched (template) | JoJo's Bizarre Adventure Part 6: Stone Ocean | — | Shared parser: chapters, pages |
| sushiscan.net | — | http | fr | No | Included in search | French manga scans | — | Search, chapters, pages |
| sxfmanga.net | ww2.sxfmanga.net (Not searched (template)) | http | — | No | Not searched (template) | Spy x Family | — | Shared parser: search, chapters, pages |
| tgmanga.com | — | http | — | No | Included in search | Tokyo Ghoul | — | Pages |
| thedragonballsuper.online | — | http | — | No | Included in search | Dragon Ball Super | — | Chapters |
| tokyoghoul.club | — | http | — | No | Included in search | Tokyo Ghoul | — | — |
| tomie-manga.com | w12.tomie-manga.com (Not searched (template)) | http | — | No | Not searched (template) | Tomie | — | Shared parser: chapters, pages |
| toonily.me | — | browser | — | No | Included in search | Manhwa focused | — | — |
| tortugaceviri.com | — | http | — | No | Not searched (template) | — | — | Shared parser: search, chapters, pages |
| trigunmanga.com | — | http | — | No | Not searched (template) | Trigun | — | Shared parser: chapters, pages |
| truemanga.com | mangamonk.com (Not searched (needs-js)) | http | — | No | Not searched (needs-js) | — | — | — |
| uchuujinmangas.com | — | http | es | No | Included in search | Spanish manga and manhwa reader | — | Search, chapters, pages |
| unopiece.com | — | http | — | No | Not searched (template) | One Piece | — | Shared parser: chapters, pages |
| uzaymanga.com | — | api | tr | No | Included in search | Turkish manga/manhwa/manhua reader | — | Search, chapters, pages |
| vagabondmanga.org | — | http | — | No | Included in search | Vagabond | — | Chapters |
| vermanhwa.com | — | http | — | No | Not searched (template) | — | — | Shared parser: search, chapters, pages |
| webtoons.com | — | http | — | No | Included in search | Official WEBTOON Originals in English, Spanish, French and German | — | Search, chapters, pages |
| witch-hat-atelier.online | — | http | — | No | Not searched (template) | Witch Hat Atelier (Tongari Boushi no Atelier) | — | Shared parser: chapters, pages |
| witch-watch.com | — | http | — | No | Not searched (template) | Witch Watch | — | Shared parser: chapters, pages |
| wurmz.net | — | http | id | No | Included in search | Indonesian manga/manhwa/manhua reader | Search, chapters, pages, image | Search, chapters, pages |
| yakshascans.com | — | http | — | No | Not searched (template) | — | — | Shared parser: search, chapters, pages |
| yuri-online.com | — | http | es | Yes | Included in search | Spanish yuri manga scans; adult titles refused | — | Search, chapters, pages |
| zazamanga.com | deathnotemanga.com (Included in search), death-note-online.com (Included in search), fairytail100yearsquest.com (Included in search), gintama.site (Included in search), initialdmanga.com (Included in search), inuyasha.net (Included in search), onepunchmanmanga.org (Included in search), readhellsing.com (Included in search), readoverlord.com (Included in search) | browser | — | No | Included in search | Also serves several redirected series sites | — | — |
| zonatmo.org | — | browser | es | No | Included in search | Spanish manga/manhwa library | Search, chapters, pages, image | Search, chapters, pages |
