# CoopSbR eşleştirilmiş CPU–GPU analizi

CoopSbR, insan–şempanze girdilerinin tamamında tek iş parçacıklı C++ referansından **5,59–29,79×** hızlı. CPU, altı küçük *Drosophila* girdisinin tamamında daha hızlı. GPU’nun bütün girdilerde öne geçtiği ilk ölçülen boyut, uniform ailede **4.096**, yarı rastgele ailede **16.384 marker**.

21 Kasım 2026 ölçümü 82 farklı girdiyi, 142 CPU–GPU çift turunu ve 1.140 zamanlı çağrıyı kapsıyor. 284 ısınma çağrısıyla birlikte her çalıştırmanın aynı arşivlenmiş reversal dizisini ürettiği bağımsız yeniden oynatma ve SHA-256 ile doğrulandı.

## Gerçek genomik girdiler

| Girdi | Marker | Reversal | CPU (ms) | GPU (ms) | CPU/GPU | Tur aralığı | GPU daha hızlı |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| *D. simulans* 2R | 2.565 | 21 | 0,154 | 1,150 | 0,14× | 0,13–0,33× | 0/6 |
| *D. simulans* 3L | 2.505 | 19 | 0,140 | 1,124 | 0,12× | 0,12–0,13× | 0/6 |
| *D. simulans* 3R | 3.109 | 89 | 0,697 | 1,555 | 0,45× | 0,43–0,46× | 0/6 |
| *D. yakuba* 3L | 2.415 | 69 | 0,447 | 1,467 | 0,31× | 0,30–0,32× | 0/6 |
| *D. yakuba* 3R | 3.060 | 71 | 0,561 | 1,399 | 0,40× | 0,38–0,41× | 0/6 |
| *D. yakuba* X | 1.890 | 43 | 0,195 | 1,239 | 0,16× | 0,15–0,17× | 0/6 |
| Kromozom 1, 100 bp | 255.924 | 296 | 168,553 | 5,664 | 29,79× | 28,64–30,90× | 6/6 |
| **Kromozom 1, 250 bp** | 203.698 | 192 | 87,941 | 3,733 | 23,59× | 22,78–24,42× | 6/6 |
| Kromozom 1, 500 bp | 141.617 | 123 | 43,318 | 2,410 | 18,00× | 17,39–18,55× | 6/6 |
| Kromozom 16, 100 bp | 91.158 | 242 | 45,887 | 3,057 | 15,01× | 14,91–16,09× | 6/6 |
| **Kromozom 16, 250 bp** | 70.726 | 135 | 20,336 | 2,118 | 9,60× | 9,53–9,64× | 6/6 |
| Kromozom 16, 500 bp | 47.804 | 88 | 9,539 | 1,706 | 5,59× | 5,54–5,93× | 6/6 |

Her satırda CPU ve GPU süreleri altı tur medyanının medyanıdır. CPU/GPU sütunu tur başına eşleştirilmiş altı oranın medyanıdır. Aralık en küçük ve en büyük tur oranını verir. 250 bp birincil eşiktir. Diğer eşikler aynı iki kromozom çiftinin farklı temsilleridir.

## Sentetik girdiler

| Marker | Girdi ailesi | Medyan reversal | CPU (ms) | GPU (ms) | Medyan CPU/GPU | Girdi aralığı | GPU daha hızlı |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2.048 | Uniform | 2.036 | 11,034 | 13,802 | 0,79× | 0,78–0,85× | 0/5 |
| 2.048 | Yarı rastgele (`k = 64`) | 67 | 0,337 | 1,444 | 0,24× | 0,22–0,24× | 0/5 |
| 4.096 | Uniform | 4.080 | 44,383 | 27,646 | 1,62× | 1,60–1,74× | 5/5 |
| 4.096 | Yarı rastgele (`k = 64`) | 64 | 0,602 | 1,444 | 0,43× | 0,40–0,45× | 0/5 |
| 8.192 | Uniform | 8.176 | 177,761 | 52,215 | 3,40× | 3,28–3,58× | 5/5 |
| 8.192 | Yarı rastgele (`k = 64`) | 66 | 1,267 | 1,468 | 0,89× | 0,86–0,93× | 0/5 |
| 16.384 | Uniform | 16.370 | 714,443 | 99,688 | 7,16× | 7,06–7,20× | 5/5 |
| 16.384 | Yarı rastgele (`k = 64`) | 64 | 2,510 | 1,397 | 1,79× | 1,63–1,87× | 5/5 |
| 32.768 | Uniform | 32.749 | 2.893,611 | 205,395 | 14,09× | 14,07–14,11× | 5/5 |
| 32.768 | Yarı rastgele (`k = 64`) | 64 | 5,056 | 1,529 | 3,29× | 3,20–3,71× | 5/5 |
| 65.536 | Uniform | 65.516 | 11.639,810 | 463,412 | 25,12× | 24,57–25,19× | 5/5 |
| 65.536 | Yarı rastgele (`k = 64`) | 66 | 10,130 | 1,647 | 6,16× | 6,00–6,94× | 5/5 |
| 131.072 | Uniform | 131.049 | 46.387,009 | 1.200,717 | 38,65× | 37,76–39,07× | 5/5 |
| 131.072 | Yarı rastgele (`k = 64`) | 64 | 20,005 | 2,008 | 9,86× | 9,41–10,41× | 5/5 |

Her hücre beş farklı girdi içeriyor. Her girdi için yöntem başına üç zamanlı çağrının medyanı alındı. Önce her girdinin CPU/GPU oranı hesaplandı. Hücre medyanı ve aralığı bu beş oran üzerinden hesaplandı.

## Bulguların kapsamı

- GPU, insan–şempanze grubunda 6/6 ve *Drosophila* grubunda 0/6 girdi medyanında daha hızlı. İnsan–şempanze girdilerinin medyan oranları 5,59–29,79×. Bu, iki kromozom çiftindeki altı girdi için vaka bazlı bir bulgu.
- GPU, uniform sentetiklerde 30/35 ve yarı rastgele sentetiklerde 20/35 girdide daha hızlı. Uniform girdilerde marker sayısıyla birlikte reversal sayısı da artıyor. Yarı rastgele ailede gözlenen reversal sayısı görece sabit kalıyor. Hücreler bu iki iş yükünün boyuta göre davranışını gösteriyor.
- Kıyas, tek iş parçacıklı C++ referansını ve üç grid-geneli bariyer kullanan CoopSbR sürümünü kapsıyor. İki uygulama aynı kararı ve çıktıyı üretirken özetleme, aday değerlendirme ve bellek erişimi kendi uygulamalarına ait.

## Ölçüm ve yeniden üretim

Tek iş istasyonu kullanıldı. CPU AMD Ryzen Threadripper PRO 5965WX 24-Cores, GPU NVIDIA RTX 6000 Ada Generation, 580.178.04. Çözücü ve bağımsız kontrol uygulaması Release derlendi. GPU yapılandırması, blok başına 128 thread ve otomatik grid boyutuyla tam özet güncellemesi, yerel sanal aday değerlendirmesi ve skaler indirgemeydi. Ölçüm sürümü yalnızca CPU ile GPU’yu saran ortak süre ölçümünü ekliyor. Çözücü kaynak revizyonu `dcdc2fde817957b176d3978c7fa9e7d8a0318b24`.

Ana ölçüt `paired_wall_ms`, bellekte hazır girdiden sıralı çıktı ve reversal dizisinin ana belleğe teslimine kadar geçen çağrı süresi. CPU ve GPU için aynı saat ve çağrı sınırı kullanılıyor. Isınma, ilk CUDA başlatma maliyetini zamanlı örneklerin dışında bırakıyor. GPU’nun çağrı başına cihaz ve yerleşim sorguları, bellek ayırma, veri aktarımı ve sonuç kopyalama bu süreye dahil. Dosya okuma/yazma ve doğrulama ölçümün dışında. Kayıtlar önceki protokolün süre sınırındaki `end_to_end_ms` ve çözücü içi `sort_ms` alanlarını da içeriyor.

Gerçek girdilerde her iki yöntem için tur başına bir ısınma ve beş zamanlı çağrı ölçüldü. Altı turun üçünde CPU, üçünde GPU önce çalıştı. Sentetik girdilerin her biri için bir ısınma ve üç zamanlı çağrı ölçüldü. Yöntem sırası hücrelerde 3–2 dengelendi. Girdi ve yöntem sırası için sabit seed 42 kullanıldı.

Ölçüm koşusu 22,4 dakika sürdü. [Girdi manifesti](cases.json), [tur sonuçları](analysis/paired-rounds.csv), [girdi sonuçları](analysis/per-input.csv), [sentetik hücreler](analysis/synthetic-cells.csv), [performans grafiği](paired-speedup.pdf) ve [ham kayıtlar](raw-results.tar.gz). Grafikte dsim ve dyak, *D. melanogaster* ile karşılaştırılan sorgu türleridir. Gerçek girdi çizgileri tur aralığını, sentetik çizgiler girdi aralığını gösterir. 1× üzerindeki oranlarda GPU daha hızlıdır.
