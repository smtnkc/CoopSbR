# CoopSbR Graph yeniden kullanımı ve bariyer deneyleri

**Önceden örneklenmiş Graph’a karşı CoopSbR, *Drosophila* girdilerinde 1,47–1,57×, insan–şempanze girdilerinde 1,22–1,76× hızlandı.** Bu kıyasta her iki yöntem de tamponlarını yeniden kullandı. Ayrı fazlarla tam kopyalama kontrolüne karşı füzyon, gerçek girdilerde 1,07–1,15× hızlanma verdi. Blok içi paralel toplamayı sabit tutan karar çoğaltma kıyasında aralık 1,05–1,10× oldu.

21 Kasım 2026 ölçümü 82 farklı girdi, 142 eşleştirilmiş tur ve 1.704 yöntem/tur kombinasyonunu kapsıyor. Ana matriste 6.840 zamanlı ve 1.704 ısınma çağrısı var. Her çağrı CPU referans sertifikasıyla aynı reversal dizisini üretti ve bağımsız yeniden oynatmayı geçti. Ana ölçümler ve amortisman koşuları 20,5 dakika sürdü.

## Graph yaşam döngüsü

| Eşleştirilmiş süre oranı | Uniform | Yarı rastgele | *Drosophila* | İnsan–şempanze |
| --- | ---: | ---: | ---: | ---: |
| Graph yeni tampon / Graph kalıcı tampon, yeni Graph | 0,939–1,004× (6/7) | 1,135–1,197× (7/7) | 1,149–1,508× (6/6) | 0,999–1,121× (5/6) |
| Kalıcı tamponlarda yeni Graph / önceden örneklenmiş Graph | 1,001–1,004× (7/7) | 1,031–1,083× (7/7) | 1,059–1,241× (6/6) | 1,003–1,046× (6/6) |
| Yeni Graph / CoopSbR, tek çağrı | 1,635–1,829× (7/7) | 1,419–1,582× (7/7) | 1,414–1,533× (6/6) | 1,140–1,765× (6/6) |
| Önceden örneklenmiş Graph / 4 bariyer, kalıcı tampon | 1,422–1,574× (7/7) | 1,302–1,461× (7/7) | 1,339–1,403× (6/6) | 1,060–1,566× (6/6) |
| Önceden örneklenmiş Graph / CoopSbR, kalıcı tampon | 1,637–1,828× (7/7) | 1,475–1,617× (7/7) | 1,469–1,574× (6/6) | 1,219–1,757× (6/6) |
| 4 bariyer / CoopSbR, kalıcı tampon | 1,137–1,221× (7/7) | 1,082–1,130× (7/7) | 1,096–1,123× (6/6) | 1,105–1,180× (6/6) |

Aralıklar sentetik ailelerde yedi hücre medyanının, gerçek ailelerde altı girdi medyanının en düşük ve en yüksek değerini gösterir. Parantez, 1× üstündeki medyan sayısıdır. Her oran ilk yöntemin süresini ikinciye böler.

| Birincil 250 bp girdi | Graph yeniden kullanım (ms) | Dört bariyer kalıcı tampon (ms) | CoopSbR kalıcı tampon (ms) | Graph / CoopSbR |
| --- | ---: | ---: | ---: | ---: |
| chr1 | 4,121 | 3,101 | 2,627 | 1,570× |
| chr16 | 1,899 | 1,194 | 1,081 | 1,757× |

Mevcut Graph kipinde ölçülen örnekleme, yükleme ve kaldırma payı *Drosophila* için %4,8–12,6, insan–şempanze için %0,8–4,2. Yaşam döngüsü farkının doğrudan kontrolünde iki Graph sürümü de aynı tampon yönetimini kullanıyor. Önceden örneklenmiş Graph, aynı boyutlu kimlik ve sırasız permütasyonları art arda, ayrıca iki farklı sırasız permütasyonu ardışık olarak doğru işledi.

## Bariyer ve veri yolu kontrolleri

| Eşleştirilmiş süre oranı | Uniform | Yarı rastgele | *Drosophila* | İnsan–şempanze |
| --- | ---: | ---: | ---: | ---: |
| Özgün 5 bariyer / eşleştirilmiş 5 bariyer seri | 0,962–0,983× (0/7) | 0,971–0,988× (0/7) | 0,969–0,984× (0/6) | 0,941–0,995× (0/6) |
| 5 bariyer seri / 5 bariyer tek blokta paralel | 1,010–1,312× (7/7) | 1,004–1,187× (7/7) | 0,993–1,010× (5/6) | 1,137–1,337× (6/6) |
| 5 bariyer tek blokta paralel / 4 bariyer çoğaltılmış karar | 1,091–1,112× (7/7) | 1,039–1,079× (7/7) | 1,046–1,087× (6/6) | 1,076–1,105× (6/6) |
| Özgün 5 bariyer / 4 bariyer çoğaltılmış karar | 1,077–1,407× (7/7) | 1,054–1,229× (7/7) | 1,035–1,065× (6/6) | 1,221–1,452× (6/6) |
| 4 bariyer yerinde / 4 bariyer çift tampon, ayrı faz | 0,975–1,000× (0/7) | 0,972–0,994× (0/7) | 0,967–0,983× (0/6) | 0,946–0,987× (0/6) |
| 4 bariyer çift tampon, ayrı faz / 3 bariyer birleşik tam kopya | 1,150–1,175× (7/7) | 1,087–1,117× (7/7) | 1,073–1,125× (6/6) | 1,090–1,149× (6/6) |
| 3 bariyer birleşik tam kopya / 3 bariyer sınırlı yazma | 0,999–1,040× (6/7) | 0,991–1,021× (4/7) | 0,993–1,004× (4/6) | 1,011–1,055× (6/6) |
| 4 bariyer yerinde / 3 bariyer birleşik tam kopya | 1,132–1,175× (7/7) | 1,059–1,092× (7/7) | 1,043–1,095× (6/6) | 1,064–1,114× (6/6) |
| 4 bariyer yerinde / CoopSbR | 1,135–1,221× (7/7) | 1,070–1,103× (7/7) | 1,038–1,098× (6/6) | 1,061–1,176× (6/6) |

- Özgün seri ve eşleştirilmiş seri 5 bariyerli sürümler, iki aday ucunu önden hazırlamanın etkisini gösterir. Eşleştirilmiş seri ve tek blokta paralel 5 bariyerli sürümler, hazırlık ve karar yayını sabitken blok içi toplamayı karşılaştırır.
- 5 bariyerli tek blokta paralel sürüm ile 4 bariyerli sürümün farkı, aynı blok içi toplamayı her bloğa çoğaltmanın ve karar yayını bariyerini kaldırmanın net etkisidir.
- 4 bariyerli çift tamponlu ayrı faz sürümü ile 3 bariyerli birleşik tam kopya sürümü aynı değişmez kaynak, çift tampon, tam yazma ve sanal özetleme işini kullanır. 3 bariyerli iki birleşik sürümün karşılaştırması yazma kısıtlamasını ölçer.
- Mutlak süre farkları ve parite çevresindeki altı tur aralıkları girdi tablosunda yer alır. Sentetik hücre aralıkları, beş girdinin tam bootstrap dağılımından türetilmiş betimsel yüzde 95 aralıklarını da içerir.

## Hazırlık maliyetinin amortismanı

Aşağıdaki değerler doğrudan 1, 10 ve 100 zamanlı çağrıyla ölçülen ortalama ms/çözüm değerleridir. Kalıcı yöntemlerde bir defalık hazırlık ve kapanış, toplam süreye eklenip çağrı sayısına bölünür. Isınma çağrısı bu hesabın dışındadır. Her hücre bir ölçüm grubunu özetler.

| Girdi | Çözüm | Yeni Graph | Hazır Graph | Kalıcı 4 bariyer | Kalıcı CoopSbR |
| --- | ---: | ---: | ---: | ---: | ---: |
| chr1-min250 | 1 | 4,429 | 5,355 | 3,401 | 3,056 |
| chr1-min250 | 10 | 4,401 | 4,238 | 3,147 | 2,667 |
| chr1-min250 | 100 | 4,112 | 3,890 | 2,905 | 2,620 |
| chr16-min250 | 1 | 2,055 | 2,453 | 1,362 | 1,210 |
| chr16-min250 | 10 | 2,034 | 1,895 | 1,191 | 1,075 |
| chr16-min250 | 100 | 2,033 | 1,840 | 1,175 | 1,048 |
| dsim-3L | 1 | 0,448 | 0,747 | 0,334 | 0,333 |
| dsim-3L | 10 | 0,422 | 0,263 | 0,185 | 0,170 |
| dsim-3L | 100 | 0,428 | 0,243 | 0,169 | 0,154 |

## Yöntem ve kayıtlar

Deney NVIDIA RTX 6000 Ada Generation, 580.178.04 üzerinde, `dcdc2fde817957b176d3978c7fa9e7d8a0318b24` çözücü tabanından derlenen tek bir ikiliyle yürütüldü. GPU yöntemlerinin tümü 128 thread/blok, girdi başına aynı ortak grid boyutu, tam özet yenilemesi ve skaler sanal aday değerlendirmesi kullandı. CUDA bağlam açılışı, dosya I/O ve bağımsız replay zamanlı çağrı sınırı dışındadır. Ana uçtan uca ölçüm hazır host girdisinden host çıktılarına kadar veri transferlerini içerir. Tek çağrı sürümleri çağrı başına tampon yönetimini, yeni Graph sürümleri ayrıca kendi Graph yaşam döngülerini içerir. Kalıcı tampon ve Graph için bir defalık maliyet ayrıca kayıtlıdır.

Pilotun 200 çağrısı da doğrulandı. İki CTest grubu geçti. Yeni 5 bariyerli paralel seçim, 4 bariyerli ayrı faz ve yeniden kullanılan Graph kiplerinde çalıştırılan altı CUDA bellek ve eşzamanlama kontrolü sıfır hatayla tamamlandı. [Doğrulama özeti](validation.txt).

Gerçek girdilerin altı turunda her yöntem çifti üçer kez önce çalıştı. Her yöntem/tur için bir ısınma ve beş zamanlı çağrı vardı. Sentetiklerde her girdi başına bir tur, bir ısınma ve üç zamanlı çağrı vardı. Yöntemlerin göreli sırası beş girdili hücrelerde 3:2 dengelendi. Oranlar önce tur içinde hesaplandı. Gerçek girdiler altı tur medyanını, sentetik hücreler beş girdi medyanını verir.

[Ham kayıtlar](raw-results.tar.gz) · [Girdi düzeyi ve tur aralıkları](analysis/per-input.csv) · [Sentetik hücreler](analysis/synthetic-cells.csv) · [Zaman bileşenleri](analysis/timing-components.csv) · [Amortisman verileri](analysis/amortized.csv) · [Yeniden analiz](analyze_experiments.py).
