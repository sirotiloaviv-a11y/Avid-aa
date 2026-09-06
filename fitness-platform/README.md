# FitLife — פלטפורמת כושר ותזונה

מוצר אחד, שלוש חוויות: **מסלול נשים** (ורוד), **מסלול גברים** (כחול) ו**דשבורד ניהולי**
(SaaS כהה). הממשק עברי־ראשון, RTL מלא, ורספונסיבי ממובייל ועד דסקטופ.

הכלל העסקי המרכזי: משתמש/ת שייכ/ת למסלול אחד בלבד, וההפרדה נאכפת **בשרת** — לא
ב‑CSS, לא בהסתרת כפתורים ולא ב‑localStorage.

## הפעלה

```bash
cd fitness-platform
python3 -m fitness_platform seed            # תוכן דמו + משתמשי בדיקה
python3 -m fitness_platform serve           # http://127.0.0.1:8000
```

משתמשי הדמו (סיסמה `Aa123456`):

| אימייל | תפקיד |
| --- | --- |
| `noa@example.com` | מסלול נשים |
| `daniel@example.com` | מסלול גברים |
| `admin@example.com` | אדמין |

פקודות נוספות:

```bash
python3 -m fitness_platform routes                                   # טבלת הניתובים
python3 -m fitness_platform createadmin --email a@b.co --password …  # יצירת אדמין
python3 -m unittest discover -s tests -t .                           # חבילת הבדיקות
```

בפרודקשן מריצים מול שרת WSGI אמיתי:

```bash
gunicorn 'fitness_platform.wsgi:application' --bind 0.0.0.0:8000 --workers 4
```

## דרישות

Python 3.11+ בלבד. **אין תלויות חיצוניות** — לא בזמן ריצה ולא לבדיקות
(`sqlite3`, `wsgiref` ו‑`unittest` מהספרייה הסטנדרטית).

## מה יש בפנים

* **עמוד נחיתה** עם בחירת מסלול, ועמוד מחירים.
* **שאלון רב‑שלבי** עם ולידציה בשרת ושמירת התקדמות — אפשר לעצור ולחזור מכל מכשיר.
* **מסך "התוכנית שלך מוכנה"** לפני התשלום, ואז מנוי וסליקה.
* **דשבורד חברים**: אימון היום, תפריט, רשימת קניות, מעקב התקדמות, תוכניות,
  ספריית וידאו, קהילה, AI Coach והגדרות.
* **דשבורד ניהולי**: משתמשים, מנויים ותשלומים, ניהול תוכן (וידאו/תוכניות/מתכונים),
  מרכז בקרת AI, דוחות ויומן ביקורת.
* **מנוע התאמה אישית** דטרמיניסטי מעל ספריית תוכן מאושרת, ומעליו שכבת AI שרק
  בוחרת מתוכה — לא ממציאה תוכן ולא נותנת ייעוץ רפואי.

## ארכיטקטורה

הסבר מלא על ההחלטות — כולל למה אין Framework, איך נאכפת הפרדת המסלולים ואיפה
עוברים לספקים אמיתיים — נמצא ב־[ARCHITECTURE.md](ARCHITECTURE.md).

```
fitness_platform/
  config.py            הגדרות מסביבה (מותג, ספקים, אבטחה)
  core/                נתב, בקשה/תשובה, middleware, שגיאות
  db/                  schema.sql, חיבור, seed, repositories/
  domain/              gender.py (חוק ההפרדה), roles, subscription, onboarding, rules_engine
  services/            auth, authorization, onboarding, program, meal, analytics
    ai/                AIProvider + mock + anthropic + safety + coach
    payments/          PaymentProvider + mock + billing_service (webhooks)
    storage/           StorageProvider + local
  web/
    routes/            public, auth, onboarding, subscription, app, admin, api/
    ui/                primitives, components, charts, layouts, icons  (Design System)
  static/              css/ (tokens, base, components, layout, pages), js/, img/
tests/                 196 בדיקות, כולל חבילת בידוד המסלולים
```

## אבטחה בקצרה

| נושא | מימוש |
| --- | --- |
| הפרדת מסלולים | `domain/gender.py` + `services/authorization.py`; כל שאילתת תוכן מקבלת `gender_path` |
| הרשאות | תפקידים והרשאות ב‑`domain/roles.py`; `/admin` מאחורי `require_admin` |
| סיסמאות | PBKDF2‑HMAC‑SHA256, 240k איטרציות, salt לכל סיסמה |
| Sessions | טוקן אקראי בשרת, עוגייה `HttpOnly` + `SameSite=Lax` |
| CSRF | Double‑submit token בכל בקשה משנה־מצב (למעט webhook החתום) |
| תשלומים | גישה נפתחת רק מול webhook עם חתימה תקינה — אף פעם לא מהדפדפן |
| Rate limiting | לכל IP, ובנוסף לכל אימייל בניסיונות התחברות |
| Headers | CSP ללא `unsafe-inline`, `nosniff`, `X-Frame-Options: DENY`, HSTS בפרודקשן |
| ביקורת | כל פעולת אדמין וכל דחיית גישה נרשמות ב‑`admin_audit_logs` |
| פרטיות | מחיקת חשבון מסירה פרטים אישיים ותשובות שאלון; אין שמירת פרטי אשראי |

## מצבי הרצה (MOCK / DEVELOPMENT / PRODUCTION)

אין במערכת פונקציונליות מזויפת שנראית אמיתית. מה שעדיין לא מחובר לספק חיצוני
עובר דרך ממשק מוגדר עם מימוש mock שמסומן ככזה גם בממשק הניהול:

* **AI** — `AI_PROVIDER=mock` מרכיב תשובה מאותו תוכן מאושר שהספק האמיתי היה מקבל.
  `AI_PROVIDER=anthropic` + `AI_API_KEY` מפעיל את הספק האמיתי.
* **תשלומים** — מסך סליקה מדומה שאינו אוסף שום פרט תשלום, ומשדר webhook חתום
  דרך אותו handler של פרודקשן. בפרודקשן `PAYMENT_PROVIDER=mock` נחסם.
* **אחסון** — `StorageProvider` עם מימוש מקומי; מעבר ל‑S3/GCS הוא מחלקה אחת.
