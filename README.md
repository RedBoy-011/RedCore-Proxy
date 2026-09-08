# RedCore-Proxy

ابزار لینوکسی فارسی برای دریافت لینک‌های Subscription، تست واقعی نودها و تولید حداکثر ۸ خروجی SOCKS5 محلی برای پنل ثنایی / 3X-UI.

## روش انتخاب نود

1. دریافت و decode ساب (Base64 یا لینک‌های خطی).
2. پارس VLESS، Trojan، VMess و Shadowsocks.
3. تست هم‌زمان TCP برای حذف نودهای خاموش.
4. ساخت آزمایشی Xray برای هر دستهٔ ۸تایی.
5. تست واقعی از داخل SOCKS: اتصال SOCKS5 → TLS → درخواست HTTP به `example.com`.
6. رتبه‌بندی براساس زمان تست واقعی و نگه‌داری حداکثر ۸ نود موفق.

هیچ نودی فقط با «بازبودن پورت TCP» وارد خروجی نهایی نمی‌شود.

## پشتیبانی پروتکل

- VLESS: TCP، WS، gRPC، HTTPUpgrade، XHTTP، TLS و Reality
- Trojan
- VMess
- Shadowsocks (لینک‌های URI رایج)

Hysteria2 و TUIC به هستهٔ sing-box نیاز دارند و در این نسخهٔ Xray وارد خروجی نمی‌شوند؛ در گزارش به‌عنوان «پشتیبانی‌نشده» ثبت می‌شوند.

## نصب

پس از آپلود همهٔ فایل‌ها در ریشهٔ مخزن `RedBoy-011/RedCore-Proxy`:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/RedBoy-011/RedCore-Proxy/main/install.sh)
```

## استفاده

```bash
titan
```

یا:

```bash
titan subs add 'نام ساب' 'https://example.com/sub.txt'
titan test-subs
titan refresh
titan status
titan socks-test 10801
titan json
```

## فایل‌های سرور

| مسیر | کاربرد |
|---|---|
| `/etc/titan/subs.txt` | هر خط: `نام ساب | لینک ساب` |
| `/etc/titan/xray.json` | پیکربندی تولیدشدهٔ Xray |
| `/etc/titan/sanaei.json` | JSON آمادهٔ Outbound ثنایی |
| `/etc/titan/status.json` | گزارش نودهای انتخاب‌شده و نتیجه تست |
| `/var/log/titan/refresh.log` | لاگ اجرای پروژه |

پس از `titan refresh` فقط JSON موجود در `/etc/titan/sanaei.json` را وارد پنل کنید. اگر کمتر از ۸ نود واقعاً سالم باشد، فقط همان تعداد خروجی ساخته می‌شود.
