# RedCore-Proxy

مدیر ساب‌های VLESS، VMess و Trojan برای لینوکس. برنامه با **Python** نوشته شده و فقط برای برقراری واقعی اتصال از **Xray Core** استفاده می‌کند.

هر یک دقیقه همهٔ نودهای قابل‌پارس با SOCKS موقت Xray و اتصال واقعی HTTPS تست می‌شوند؛ سالم‌ترین حداکثر ۸ نود بر اساس زمان پاسخ انتخاب شده و به SOCKSهای لوکال مستقل تبدیل می‌شوند:

`127.0.0.1:10801` تا `127.0.0.1:10808`

هر پورت فقط به یک نود وصل است؛ هیچ load-balance یا انتخاب ساختگی وجود ندارد. دانلود ساب‌ها حداکثر هر یک ساعت یک بار انجام می‌شود و تست نودهای کش‌شده هر یک دقیقه تکرار می‌شود. اگر یک دور تست بیش از یک دقیقه طول بکشد، دور بعدی پس از پایان اجرای قبلی آغاز می‌شود تا تست‌ها هم‌زمان و مخرب نشوند.

## نصب

روی Ubuntu/Debian یا Fedora/RHEL با کاربر root اجرا کنید:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/RedBoy-011/RedCore-Proxy/main/install.sh)
```

نصب‌کننده **هیچ ساب نمونه‌ای** اضافه نمی‌کند.

## شروع سریع

```bash
redcore-proxy
```

یا بدون منو:

```bash
redcore-proxy subs add 'نام دلخواه' 'https://example.com/your-subscription'
redcore-proxy test-subs
redcore-proxy refresh
redcore-proxy status
redcore-proxy json
redcore-proxy socks-test 10801
```

در منو گزینهٔ ۵ تمام نودها را تست، مرتب و خروجی‌ها را می‌سازد. اولین اجرا ممکن است چند دقیقه طول بکشد، چون اتصال واقعی همهٔ نودها بررسی می‌شود.

## JSON برای پنل ثنایی / 3X-UI

پس از یک اجرای موفق:

```bash
redcore-proxy json
```

یا فایل زیر را در Outbounds پنل وارد کنید:

```text
/etc/redcore-proxy/sanaei.json
```

نمونهٔ یک خروجی:

```json
{
  "tag": "Socks_1_redcore",
  "protocol": "socks",
  "settings": {
    "servers": [{"address": "127.0.0.1", "port": 10801, "users": []}]
  }
}
```

## مسیرها و زمان‌بندی

| مورد | مسیر / رفتار |
|---|---|
| فهرست ساب‌ها | `/etc/redcore-proxy/subs.txt` |
| کش نودهای دانلودشده | `/etc/redcore-proxy/nodes.json` |
| کانفیگ نهایی Xray | `/etc/redcore-proxy/config.json` |
| خروجی JSON پنل | `/etc/redcore-proxy/sanaei.json` |
| نتیجهٔ آخر | `/etc/redcore-proxy/status.json` |
| لاگ | `/var/log/redcore-proxy/refresh.log` |
| تست پینگ و سورت | هر ۱ دقیقه |
| دانلود مجدد ساب | حداکثر هر ۱ ساعت |

برای دیدن وضعیت زمان‌بندی:

```bash
systemctl list-timers redcore-proxy-refresh.timer
```

برای مشاهدهٔ لاگ زنده:

```bash
redcore-proxy logs
```

## نکات

- فقط `vless://`، `vmess://` و `trojan://` پردازش می‌شوند.
- لینک‌های Base64 و لینک‌های raw GitHub پشتیبانی می‌شوند؛ لینک `github.com/.../blob/...` نیز خودکار به raw تبدیل می‌شود.
- اگر کمتر از ۸ نود واقعاً سالم باشد، فقط همان تعداد پورت ساخته می‌شود.
- تست موفق به معنای برقراری SOCKS، TLS و دریافت پاسخ HTTPS است؛ صرفاً باز بودن TCP محسوب نمی‌شود.
