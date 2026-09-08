# RedSocKs5-NordVPN

GitHub: https://github.com/RedBoy-011/RedSocKs5-NordVPN

## معرفی سرویس

این پروژه با یک حساب NordVPN و **Service Credentials**، چند تونل مستقل می‌سازد و برای هر تونل یک SOCKS5 داخلی با پورت ثابت ارائه می‌دهد. اسکریپت کشورها را یکی‌یکی تست می‌کند؛ کشور خراب کنار گذاشته می‌شود و تا رسیدن به تعداد سالم ادامه می‌دهد. در پایان کشور واقعی هر پورت نمایش داده می‌شود.

حداکثر ۷ لوکیشن قابل انتخاب است. روی سرورهای کم‌منبع، ۳ تا ۵ تونل پایدارتر از ۷ تونل است.

راه‌اندازی پنج اتصال مستقل NordVPN روی Linux و ارائهٔ SOCKS5 داخلی با پورت‌های ثابت؛ مناسب استفاده در پنل‌ها، crawlerها و سرویس‌هایی که برای هر لوکیشن یک proxy جداگانه نیاز دارند.

> این پروژه برای استفادهٔ قانونی و مطابق قوانین NordVPN طراحی شده است. محدودیت تعداد اتصال و شرایط سرویس خود را رعایت کنید.

## امکانات

- پنج تونل مستقل NordVPN با Docker Compose
- پورت SOCKS5 ثابت برای هر لوکیشن
- تغییر کشورها فقط با ویرایش `.env`
- جداسازی مسیر شبکهٔ هر پروکسی؛ ترافیک یک کشور از کشور دیگر عبور نمی‌کند
- راه‌اندازی مجدد خودکار کانتینرها
- مناسب سرور Ubuntu/Debian

## لوکیشن‌های پیش‌فرض

کشورهای پیش‌فرض نزدیک ترکیه انتخاب شده‌اند، اما «سریع‌ترین» کشور را نمی‌توان از قبل تضمین کرد؛ سرعت به ظرفیت سرور NordVPN، مسیر ISP و زمان تست بستگی دارد.

| نام | کشور | SOCKS5 محلی |
|---|---|---|
| DE | Germany | `127.0.0.1:1081` |
| GR | Greece | `127.0.0.1:1082` |
| BG | Bulgaria | `127.0.0.1:1083` |
| RO | Romania | `127.0.0.1:1084` |
| AT | Austria | `127.0.0.1:1085` |

کشورها را می‌توان به‌طور مستقل به کشور دیگری تغییر داد و پورت متناظر ثابت می‌ماند.

## پیش‌نیازها

- Linux با Docker Engine و Docker Compose Plugin
- دسترسی root یا کاربری عضو گروه `docker`
- فعال بودن `/dev/net/tun`
- NordVPN Service Credentials

### نکته دربارهٔ توکن

توکن ورود اپلیکیشن NordVPN با اطلاعات اتصال دستی OpenVPN یکی نیست. در این پروژه باید از **Nord Account → NordVPN → Set up NordVPN manually**، مقدار Service username و Service password را دریافت کنید. توکن خصوصی را در GitHub، README یا فایل commitشده قرار ندهید.

## نصب سریع

### راه‌اندازی با منوی تعاملی

برای واردکردن Service Credentials، انتخاب پنج کشور و تعیین پورت‌های ثابت:

```bash
chmod +x RedSocKs5
./RedSocKs5
```

منو در ابتدا حالت احراز هویت را می‌پرسد: Token برای CLI رسمی NordVPN یا Service Credentials برای چند SOCKS مستقل. حالت Token فقط یک مسیر VPN فعال دارد؛ برای چند لوکیشن هم‌زمان باید حالت Service Credentials را انتخاب کنید. در حالت چند SOCKS، برای هر پورت کشورها به‌ترتیب امتحان می‌شوند و اسکریپت با اولین تونل سالم ادامه می‌دهد؛ اگر کشوری قطع باشد، فرایند متوقف نمی‌شود. در پایان کشور نهایی هر پورت و تعداد تونل‌های سالم نمایش داده می‌شود.

```bash
git clone https://github.com/RedBoy-011/RedSocKs5-NordVPN.git RedSocKs5-NordVPN
cd RedSocKs5-NordVPN
cp .env.example .env
nano .env
docker compose pull
docker compose up -d
docker compose ps
```

### نصب تک‌خطی

```bash
curl -fsSL https://raw.githubusercontent.com/RedBoy-011/RedSocKs5-NordVPN/main/install.sh | sudo bash
```

این دستور همهٔ مراحل را خودکار انجام می‌دهد: نصب Git و ابزارهای لازم، دریافت یا به‌روزرسانی امن پروژه، پشتیبان‌گیری از تغییرات محلی و اجرای تعاملی منوی `RedSocKs5`. منو از `/dev/tty` می‌خواند تا هنگام اجرای `curl | bash` ورودی‌ها گم نشوند. اگر پوشهٔ پروژه از قبل وجود داشته باشد، دوباره `git clone` اجرا نمی‌شود.

در `.env` این دو مقدار را وارد کنید:

```dotenv
NORDVPN_USERNAME=service_username
NORDVPN_PASSWORD=service_password
```

فایل `.env` محرمانه است و نباید commit شود.

## تنظیم کشور و پورت

نمونه:

```dotenv
LOC_DE=Germany
LOC_GR=Greece
LOC_BG=Bulgaria
LOC_RO=Romania
LOC_AT=Austria

PORT_DE=1081
PORT_GR=1082
PORT_BG=1083
PORT_RO=1084
PORT_AT=1085
```

پس از تغییر کشورها:

```bash
docker compose up -d --force-recreate
```

## استفاده در پنل

اگر پنل روی همین سرور اجرا می‌شود، برای هر ورودی این مقادیر را بدهید:

```text
Proxy type: SOCKS5
Host: 127.0.0.1
Port: 1081 تا 1085
```

برای DNS و دامنه‌ها از حالت `SOCKS5-HOSTNAME` استفاده کنید تا resolve نیز داخل تونل انجام شود.

تست نمونه:

```bash
curl --socks5-hostname 127.0.0.1:1081 https://ifconfig.me
curl --socks5-hostname 127.0.0.1:1082 https://ifconfig.me
```

پروکسی داخلی به‌صورت پیش‌فرض بدون احراز هویت اجرا می‌شود و فقط روی localhost در دسترس است. اگر پنل username/password می‌خواهد، باید متغیرهای `REQUIRE_AUTH=true`، `PROXY_USER` و `PROXY_PASSWORD` را برای سرویس SOCKS تنظیم کنید.

## بررسی وضعیت و لاگ‌ها

```bash
docker compose ps
docker compose logs -f vpn-de
docker compose logs -f vpn-gr
docker compose restart
```

هر سرویس VPN باید پس از برقراری تونل در وضعیت `healthy` قرار بگیرد. اگر یک کشور در دسترس نبود، مقدار آن را به نام کشور دیگری تغییر دهید.

## مصرف منابع

هر تونل OpenVPN CPU و RAM مصرف می‌کند. روی سرورهای ۱ vCPU و ۲GB RAM، اجرای پنج تونل ممکن است سنگین باشد. برای شروع می‌توانید فقط سه سرویس را فعال کنید یا کشورها را کم کنید.

## امنیت

- `.env` را در Git commit نکنید.
- دسترسی SOCKS را فقط روی `127.0.0.1` نگه دارید.
- اگر نیاز به دسترسی از سرور دیگر دارید، از SSH tunnel یا فایروال محدود به IPهای مشخص استفاده کنید؛ پورت SOCKS را عمومی باز نکنید.
- در صورت افشای توکن یا Service Credentials، آن‌ها را در Nord Account تعویض کنید.

## مجوز

این پروژه با مجوز MIT منتشر می‌شود؛ فایل `LICENSE` را متناسب با سیاست مخزن خود اضافه کنید.

## پورت‌های لوکیشن هفتمرحله‌ای

```text
1081 Germany   | 1082 Romania | 1083 Bulgaria | 1084 Austria
1085 Italy     | 1086 France  | 1087 Poland
```

برای تعمیر تونل‌های خراب، اجرای دوبارهٔ منو و انتخاب همان تعداد لوکیشن کافی است؛ اسکریپت کشورها را دوباره تست می‌کند و اولین گزینهٔ سالم را جایگزین می‌کند:

```bash
sudo ./RedSocKs5
```
