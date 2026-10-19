# שלב 1: מחקר שוק והתמצאות טכנית

**פרויקט:** אלטרנטיבת Windows בקוד פתוח לאפליקציית Mac בשם Tangerine
**תאריך:** 19.10.2026
**סטטוס:** ✅ אושר ב-19.10.2026. ההחלטות שהתקבלו מפורטות ב-§7. לפני שלב 2 רץ spike זמני.

**מקרא תגיות:**
- ✅ מאומת במקור ראשוני: תיעוד Microsoft, קוד המקור של Qt, App Store, GitHub API, או בדיקה מקומית
- 🔶 מוסק
- ❔ לא מאומת: מקור משני יחיד, או שרק ניסוי יכריע

---

## תקציר

1. **Tangerine הוא מוצר חדש מאוד.**
   - שמו המלא "Tangerine: File Converter", של LEAP STUDIO. הושק ב-7.9.2026, והגרסה הנוכחית היא v2.0.1 מ-17.10.2026.
   - איך משתמשים: מחזיקים Shift תוך כדי גרירת קובץ ב-Finder, ומופיעה סביב הסמן גלגלת של פורמטי יעד.
   - מחיר: 20 קבצים ראשונים בחינם, ואחר כך $29.99 חד-פעמי. רץ רק על macOS 13 ומעלה עם Apple silicon.
2. **ב-Windows כבר יש מתחרים.**
   - תוך 5 שבועות מההשקה הופיעו חמישה שיבוטים בקוד פתוח.
   - המוביל הוא **Filee**: C# ו-Avalonia, רישיון MIT, כ-4,000 כוכבים בשלושה שבועות, וגרסה חדשה כל 1–3 ימים.
   - שיבוט אחר, tangerine-windows, כתוב בדיוק ב-stack שלנו (Python ו-PySide6). יש לו 0 כוכבים.
   - **מסקנה:** אי אפשר לנצח בזה שנהיה ראשונים, ולכן צריך בידול (ראו §5, החלטה 1).
3. **טכנית זה בר-ביצוע.** לא צריך הרשאות אדמין, DLL injection או shell extension.
   - זיהוי תחילת הגרירה וקבלת נתיבי הקבצים הם שני מנגנונים נפרדים.
   - הזיהוי: Raw Input או WH_MOUSE_LL.
   - קבלת הנתיבים: חלון ה-overlay עצמו הוא יעד OLE לשחרור (drop target), ו-Qt כבר עוטף את זה בעצמו.
4. **⚠️ ממצא בטיחות קריטי.**
   - ב-Explorer, ‏Shift+גרירה פירושו "העבר" (Move).
   - כש-Shift לחוץ, Qt מקבל drop כ-MoveAction כברירת מחדל, ו-Explorer **מוחק את קובץ המקור**.
   - זה כבר קרה באפליקציה אמיתית: ב-Avidemux נמחקו קבצים מכרטיס SD ללא אפשרות שחזור.
   - לכן חובה לכפות CopyAction בכל drop.
5. **הסיכון הפתוח העיקרי:** האם חלון שמופיע מתחת לסמן *באמצע* גרירה מקבל DragEnter, ובאמינות.
   - התיעוד והתקדימים מצביעים שכן, אבל רק ניסוי יכריע.
   - מוצע spike זמני לבדיקה (§3.9).
6. **Stack מומלץ:** Python 3.12, ctypes, ‏Pillow ו-FFmpeg, ואריזה ב-PyInstaller.
   - **שינוי מה-brief:** אני ממליץ על **PySide6 (LGPL) במקום PyQt6**, שבחרת.
   - הסיבה: PyQt6 הוא GPLv3, ולכן מחייב את כל הפרויקט להיות GPL.
   - PyQt6 עם GPLv3 הוא עדיין מסלול קוד פתוח לגיטימי. המחיר היחיד הוא ויתור על רישוי מתירני. ההחלטה שלך (§5, החלטה 2).

---

## 1. ניתוח Tangerine המקורית

### 1.1 זיהוי המוצר

| פרט | ערך | |
|---|---|---|
| שם | Tangerine: File Converter ("Compress video, images & PDFs") | ✅ App Store |
| מוכר / מפתח | LEAP STUDIO; מפתח יחיד, ‎@th2049 ב-X | ✅ |
| אתר | tangerineformac.com | ✅ (iTunes API) |
| השקה | 7.9.2026 (הורדה ישירה); ב-App Store מ-24.9.2026 | ✅ |
| גרסה נוכחית | 2.0.1, מ-17.10.2026 | ✅ |
| ציבוריות | פוסט ההשקה ב-X: כ-121 אלף צפיות. פוסט ה-App Store: כ-412 אלף צפיות. Product Hunt: מקום 17 ביום ההשקה | ✅ |

> אין קשר ל-"Tangerine!" של Potion Factory, אפליקציית מוזיקה מ-2006.

### 1.2 מנגנון ההפעלה וה-workflow

- **שלוש גלגלות, כל אחת מופעלת במקש אחר בזמן גרירה:**
  - **Convert:** ‏Shift. ‏✅
  - **Tools:** ‏Option+Shift. ‏✅
  - **Actions:** ‏Control (נוסף ב-v2.0). ‏✅
- **סתירה במקורות:** לפי האתר הרשמי (כפי שמנועי חיפוש מציגים אותו) לוחצים לחיצה קצרה על Shift, ‏Command מפעיל את Tools, והגלגלת **נשארת פתוחה** אחרי שחרור המקש עד drop או ביטול. ❔
  - **מסקנה:** גם במקור ערכת המקשים לא יציבה, כנראה השתנתה בין גרסאות.
  - הרעיון היציב: מקש שנלחץ באמצע גרירה, וגלגלת נפרדת לכל מקש.
- **אפשר לשנות את הקיצורים** לפי שני מקורות משניים. ❔
- **ניווט במקלדת:** חיצים לבחירה, Enter לביצוע, Esc לביטול. ❔
- **בלי גרירה:** לחיצת Enter על קובץ מסומן פותחת את הגלגלת. ❔
- **מקור הגרירה:** מתועד רק Finder ושולחן העבודה. ✅ לא נמצא מידע על גרירה מאפליקציות אחרות.

### 1.3 הגלגלת

- תלויה בהקשר: מוצגים רק פורמטים וכלים שמתאימים לסוג הקובץ. ✅
- מופיעה סביב הסמן. ✅
- הפרוסה שמתחת לסמן מודגשת. 🔶 (בהערות של v2.0 תוקן "wheel highlight lag".)
- MacGeneration מתארים "גלגלת קטנה". ❔
- **לא ידוע:**
  - מספר הפרוסות
  - האם יש קינון או "עוד…"
  - מה יש במרכז
  - סגנון ה-blur והאנימציה

  (את זה אפשר לחלץ מסרטוני הדמו, ראו §1.8.)

### 1.4 יכולות ✅ (App Store, v2.0.1)

**Convert:**
- **תמונות:** JPEG, ‏PNG, ‏HEIC, ‏WebP, ‏TIFF, ‏BMP, ‏SVG, ‏GIF, ‏PDF
- **וידאו:** MP4, ‏MOV, ‏MKV, ‏AVI, ‏WMV, ‏WebM
- **אודיו:** MP3, ‏M4A, ‏WAV, ‏FLAC, ‏OGG, ‏Opus, ‏AIFF
- **מסמכים, כתוביות וארכיונים:** PDF, ‏TXT, ‏DOCX, ‏SRT, ‏VTT, ‏ZIP, ‏TAR, ‏GZIP, ‏RAR
- **נוספו ב-v2.0:** EPUB, ‏Word, ‏Pages, ‏PowerPoint, גיליונות

**Tools:**
- דחיסה: לפי אחוז, או לגודל קובץ יעד מדויק
- תמונה: חיתוך, כוונון, הערות, השחרה (redact)
- וידאו: trim, ‏crop, מהירות, פיצול, איחוד, צילום פריים
- אודיו: נרמול, trim, ‏bleep, ערוצים
- metadata: קריאה, עריכה ומחיקה
- PDF: מיזוג, פיצול וסידור מחדש; יצירת PDF וקולאז' מתמונות
- קריאת QR

**Actions:** ‏AirDrop, ‏Float (מדף צף), ‏Copy, ‏Move, ‏Copy Path, ‏Terminal

**היקף לפי האתר:** 275 המרות, 26 כלים, 6 פעולות. ❔

**אין** ראיות ל-presets, ‏workflows מותאמים, scripting, plugins או Shortcuts. ❔ משתמשים ביקשו presets.

### 1.5 פלט, משוב ופרטיות

- נוצר **עותק חדש ליד המקור, והמקור לא משתנה.** ✅
- תבנית השם כנראה `<name> <Action>.<ext>` (למשל "tangerine tree Cropped.png"). 🔶
- אפשר לעבד כמה קבצים יחד. לכל משימה נפתח חלון התקדמות קטן, ובסוף הקובץ מוצג ב-Finder. ✅
- אפליקציית menu bar. ✅
- עיבוד מקומי בלבד, בלי העלאה לענן. ✅
- גודל ההתקנה 97.6MB, כנראה בגלל codecs שבאים איתה. 🔶

### 1.6 מה עובד ומה לא

**שבחים:**
- מהירות (HEIC→JPG)
- פרטיות (עיבוד מקומי)
- תשלום חד-פעמי
- גימור ("רהוטה מאוד" לפי MacG)

**ביקורת:**
- השהיה בפתיחת הגלגלת על M1 (MacG; תוקן חלקית ב-v2.0)
- תפריט הכלים צפוף ודורש onboarding
- "$30 זה יקר"
- היו באגים של "אפשרויות המרה מוסתרות" (תוקנו ב-1.4 וב-2.0.1)

**רלוונטי לנו:** בתגובות ב-X היו מי שכתבו שיעדיפו חלופה בקוד פתוח, והוגשה בקשה פומבית לשיבוט ל-Windows. ❔/✅

### 1.7 אפליקציות Mac קרובות (להבנת המיצוב)

- **Filepane** (Setapp): גרירה מציגה דיסקית ליד הסמן, ואחריה סרגל פעולות לפי סוג הקובץ. הכי קרוב רעיונית.
- **Dropover:** ניעור הסמן בזמן גרירה פותח מדף צף עם Instant Actions. ה-"Float" של Tangerine חופף לזה.
- **Permute 4:** ממיר מדיה מבוסס חלון ותור. Tangerine מתחרה בו בכך שאין חלון בכלל.
- **Clop:** אופטימיזציה ודחיסה אוטומטית בהעתקה או ב-drop.

### 1.8 פערי ידע

- **האתר הרשמי נחסם** על ידי מסנן התוכן (Fortinet) ברשת המקומית, וגם עותק ה-Wayback שלו. כל ציטוט "מהאתר" מגיע מתקצירים של מנועי חיפוש ולכן מסומן ❔.
- **פרטי ה-UI של הגלגלת** (מספר פרוסות, מרכז, אנימציה) אפשר לחלץ מ-3 סרטוני הדמו של המפתח: קבצי MP4 של כ-20 שניות ב-video.twimg.com. ffmpeg מותקן מקומית. **הורדה רק באישורך**, וזה רלוונטי לשלב 3.

---

## 2. האקוסיסטם של Windows

### 2.1 טבלת השוואה (נתוני GitHub נבדקו ב-19.10.2026)

| כלי | טריגר | היקף | רישיון / stack | פעילות | פער מול הקונספט |
|---|---|---|---|---|---|
| **Filee** | ‏**Ctrl**+גרירה פותחת "donut" ליד הסמן. יש גם drop-zone, תפריט Explorer, ‏Send To, ‏CLI ו-watch folders | 244 פורמטים; מנועים יורדים לפי דרישה | MIT; ‏C# ‏.NET 10 + Avalonia | ‏4,038★, נוצר 29.9, ‏v1.11.0 מ-17.10 | קרוב מאוד. לא חתום. באג פתוח של אובדן ה-hook. לא עובד מאפליקציית Files |
| **tangerine-windows** | ‏Shift+גרירה = convert, ‏Alt+Shift = tools | תמונות, AV, ‏PDF, ‏Office, ארכיונים | MIT; **Python + PySide6** + FFmpeg | ‏0★, ‏v1.10.2 מ-9.10 | שיבוט ישיר. Win11 בלבד, כ-246MB, לא חתום. לפי הערות הגרסה שלו לא נבדק ידנית ב-Explorer. השם מסוכן מבחינת סימן מסחרי |
| **ZestDrop** | ‏Shift+גרירה, ‏Ctrl+Shift = tools | תמונות, AV, מסמכים (דורש Office), ‏OCR | MIT; ‏C# WPF + backend ב-Python | ‏12★, ‏v1.0.0 | מזהה ב-polling, רק מ-Explorer. כ-262MB. יש listing ב-Store |
| **KiwiConvert** | ‏Shift+גרירה (LL mouse hook) | תמונות, AV, ‏PDF | MIT (FFmpeg עצמו GPL); Tauri/Rust | ‏0★, ‏push יחיד ב-29.9 | נראה נטוש |
| **Convertino** | ‏Alt+קליק ימני או Ctrl+Alt+C, **בלי גרירה** | רחב מאוד; undo, ‏CLI, ‏MCP | GPL-3.0; Tauri/Rust | ‏1★, ‏v0.2.11 מ-18.10 | גלגלת בלי גרירה |
| **File Converter** (Tichau) | תפריט הקשר | מדיה, תמונות, PDF | GPL-3.0; C# | ‏15.4k★, ‏v2.2 מ-2.2026 | אין גרירה ואין גלגלת. ב-Win11 מופיע רק תחת "Show more options" (issues ‏#598, ‏#211 פתוחים) |
| **PowerToys** (Image Resizer, Advanced Paste) | קליק ימני / Win+Shift+V | שינוי גודל; הדבקת clipboard כקובץ, transcode ל-mp3/mp4 | MIT | פעיל | התיעוד עצמו אומר: "This isn't a file type conversion tool" |
| **Kando** | קיצור מקלדת גלובלי | pie menu להפעלת אפליקציות ופקודות | MIT; Electron | ‏6.5k★, ‏v3.0.0 | ה-UX הכי טוב בתחום ה-pie menus, אבל אין בו drop של קבצים |
| **DropPoint, Dropshelf, Holdem, Edge-Drop** | קיצור / ניעור / קצה המסך | מדפים זמניים | שונים | פעילים | מדף בלבד, בלי המרה |
| **XnConvert, Converseen, Shutter Encoder, HandBrake** | גרירה לחלון האפליקציה | המרת אצווה | שונים | פעילים | מבוססי חלון |

### 2.2 Filee: המתחרה האמיתי

- מהיר מאוד בפיתוח, ומכסה גם macOS ו-Linux (שעדיין ב-preview).
- **נקודות חולשה (✅ מ-GitHub):**
  - לא חתום (SmartScreen מזהיר). יש PR פתוח לחתימה עם Certum.
  - PR ‏#126: אחרי retry של ה-hook, ‏Ctrl+גרירה מפסיקה לפתוח את ה-donut.
  - Issue ‏#124: לא עובד מאפליקציית Files.
  - Issue ‏#127: ‏timeout בהמרת EPUB→PDF.
- **ההתנהגות של Ctrl:** ב-Explorer, ‏Ctrl+גרירה = העתקה. לכן אם ה-donut לא מופיע והמשתמש משחרר מעל תיקייה, המצב הגרוע ביותר הוא עותק מיותר.

### 2.3 ממצאי פלטפורמה שמשפיעים על ה-UX

- **מגש הגרירה של Windows 11 (Drag/Drop Tray):**
  - נוסף במאי 2025 (KB5058499): גרירת קובץ לראש המסך פותחת מגש של יעדי שיתוף.
  - **הוסר** ב-KB5121003 ב-11.8.2026, אחרי תלונות שהוא "קופץ" בגרירות רגילות. Microsoft הודיעו שהם "ממשיכים להעריך".
  - **לקח:** ההפעלה חייבת להיות מותנית במקש, ולא בכל גרירה. כדאי גם להתרחק מקצה המסך העליון.
- **מקשי ה-modifier של Explorer** ✅ (תיעוד IDropTarget::DragOver):

  | מקש בזמן גרירה | פעולה ב-Explorer |
  |---|---|
  | ללא מקש | Move בתוך אותו כונן, Copy בין כוננים |
  | Shift | **תמיד Move** |
  | Ctrl | Copy |
  | Ctrl+Shift | Link (קיצור דרך) |
  | Alt | Link (קיצור דרך) |

  - כל השיבוטים "דורסים" אחד מהמקשים האלה.
  - בנוסף, Alt+גרירה תפוס על ידי PowerToys Grab And Move.
  - אף שיבוט לא מתעד מה קורה ל-drop כשמבטלים את הגלגלת.
- **תפריט ההקשר של Win11:** כדי להופיע ברמה העליונה צריך IExplorerCommand וזהות חבילה (sparse package או MSIX). verbs קלאסיים מופיעים רק תחת "Show more options". ✅

### 2.4 הפער בשוק: במה אפשר לנצח

1. **אמון והפצה:** אף שיבוט לא חתום ב-Authenticode, ואף אחד לא מופץ ב-winget או ב-Scoop.
2. **בטיחות:** אף אחד לא מתעד הבטחה של "לעולם לא Move ולעולם לא דריסה", או ביטול שבאמת לא עושה כלום.
3. **מקשי הפעלה:** אף אחד לא מציע טריגר שאפשר להגדיר, עם התנהגות מתועדת מול מקשי Explorer.
4. **מקורות גרירה:** כולם מתעדים רק Explorer ושולחן העבודה. אף אחד לא תומך בתמונות מהדפדפן, בקבצים מצורפים מ-Outlook, בקבצים מתוך zip או ב-Files / Directory Opus.
5. **אמינות הזיהוי:** אף אחד לא מתעד התנהגות עם חלונות elevated, ריבוי מסכים או DPI מעורב.
6. **הרחבה בפייתון:** לא נמצא אף כלי שמאפשר לקהילה לכתוב ממיר או פעולה חדשה בכמה עשרות שורות. 🔶 זה בידול טבעי לפרויקט Python, ותואם את מיילסטון "מערכת הרחבות".

**לא בידול**, כי כבר קיים אצל לפחות שיבוט אחד:
- גלגלת כלים
- batch
- undo
- cross-platform
- הורדת מנועים לפי דרישה

---

## 3. היתכנות טכנית

### 3.1 העיקרון: שני מנגנונים נפרדים

```
 (A) זיהוי: "התחילה גרירה + המקש לחוץ"     (B) נתונים: "אילו קבצים נגררים"
 ─────────────────────────────────────     ─────────────────────────────────
 ניטור קלט גלובלי (Raw Input / LL hook)    החלון שלנו הוא ה-drop target של OLE
 לא רואה את תוכן הגרירה                     רק כך מקבלים IDataObject / CF_HDROP
 תפקידו: להציג את ה-overlay בזמן            תפקידו: לקבל נתיבים ולבחור פרוסה
```

אין API מתועד לקריאה "מהצד" של ה-IDataObject של תהליך אחר. ‏DoDragDrop מוסר אותו רק ל-IDropTarget של החלון שמתחת לסמן. ✅ ([DoDragDrop](https://learn.microsoft.com/en-us/windows/win32/api/ole2/nf-ole2-dodragdrop))

> ⚠️ **ממצא סותר מקוד של מתחרה (❔):** tangerine-windows (Python + PySide6) קורא את רשימת הקבצים *לפני* ה-drop.
> - **מה הקוד עושה** (`tangerine/dragfiles.py`): קורא ל-`OleGetClipboard`, בודק שיש פורמט `InShellDragLoop`, ואז קורא `CF_HDROP`.
> - **מה הוא טוען:** ש-Explorer מפרסם את ה-data object ב-OLE clipboard בזמן גרירה.
> - **איך הוא מזהה גרירה:** ‏polling של `GetAsyncKeyState` ו-`GetCursorPos` ב-QTimer, **בלי hooks בכלל**.
> - **חולשה:** כשהפורמט חסר ("some Windows builds do not publish the loop format"), הקוד מוותר על הבדיקה וקורא כל CF_HDROP שנמצא ב-clipboard. זה עלול להחזיר קבצים ישנים מ-Ctrl+C קודם.
> - **ההשלכה:** אם הטענה נכונה, זו חלופה ללא hooks, ידידותית יותר לאנטי-וירוס. היא לא מתועדת, ולפי הערות הגרסה של הפרויקט עצמו לא נבדקה ידנית ב-Explorer. **ה-spike יבדוק אותה (§3.9).**
>
> **עדכון אחרי ה-spike:** ❌ הטענה הופרכה ב-build 26200. ב-6 גרירות מ-Explorer, ה-clipboard לא הכיל אף פעם `InShellDragLoop` או `CF_HDROP`. הפירוט ב-[phase-1b-spike-results.md](phase-1b-spike-results.md), §6.

### 3.2 קבלת הנתיבים: OLE Drag and Drop דרך Qt

- **Qt עוטף IDropTarget בעצמו** (`QWindowsOleDropTarget`), כך שלא צריך COM ישיר. ✅ (qtbase)
  - `RegisterDragDrop` נקרא כשנוצר החלון הנייטיבי של top-level.
  - **זה עובד רק לסוגי חלון Window, ‏Dialog, ‏Popup ו-Tool. לחלונות `Qt.ToolTip` ו-`Qt.SplashScreen` אין drop target.**
- **CF_HDROP הופך ל-`text/uri-list`.** בקוד: `mimeData().urls()` ואז `.toLocalFile()`. ✅
- Qt משתמש ב-IDropTargetHelper, כך שתמונת הגרירה של Explorer מצוירת מעל החלון שלנו. ✅
- **ה-Drop סינכרוני בין התהליכים:** ‏Explorer קפוא עד שה-dropEvent חוזר. ✅
  - לכן dropEvent רק מעתיק את הנתיבים ואת מזהה הפרוסה ומכניס משימה לתור. שום עיבוד בתוכו.
- **קבצים וירטואליים** (מצורפים מ-Outlook, תוכן zip, FTP) מגיעים כ-`FileGroupDescriptorW` ו-`FileContents`.
  - נגישים ב-Qt דרך `application/x-qt-windows-mime;value="..."`, אבל כל הקובץ נטען לזיכרון.
  - התיקון לתיקיות zip (QTBUG-126980) קיים רק מ-Qt 6.11. ✅
  - **לא ב-MVP.**
- **גרירה מהדפדפן** מגיעה כ-URL, ‏CF_HTML או נתוני תמונה. ✅ האם Chrome מספק גם קובץ זמני ב-CF_HDROP? ❔ **לא ב-MVP.**

### 3.3 ⚠️ בטיחות: ‏Shift = Move = מחיקת המקור

שרשרת הכשל (כל חוליה מאומתת ✅):

1. כש-Shift לחוץ, ‏`QDropEvent` מציע `MoveAction`, ולכן **גם `accept()` רגיל מסוכן**, לא רק `acceptProposedAction()`. (qevent.cpp, ‏qplatformdrag.cpp)
2. אם Qt קיבל את ה-drop כ-MoveAction, הוא מחזיר ל-Explorer ‏`DROPEFFECT_MOVE` ושומר `CFSTR_PERFORMEDDROPEFFECT = MOVE`. (qwindowsdrag.cpp)
3. לפי כלל ה-"unoptimized move", המקור **מוחק את הקובץ המקורי**. ([Shell Data Scenarios](https://learn.microsoft.com/en-us/windows/win32/shell/datascenarios))
4. **תקדים:** ב-Avidemux (אפליקציית Qt), ‏Shift+גרירה מ-Explorer מחקה קבצים מכרטיס SD. התיקון (commit ‏`ac6f21c`) החליף את `acceptProposedAction()` ב-`setDropAction(Qt::CopyAction); accept();`.

**כללי חובה לפרויקט:**
- ב-`dragEnterEvent`, ‏`dragMoveEvent` ו-`dropEvent`:
  - אם `possibleActions()` כולל Copy: ‏`setDropAction(Copy)` ואז `accept()`.
  - אחרת, אם הוא כולל Link: ‏`setDropAction(Link)` ואז `accept()`.
  - אחרת: `ignore()`.
- אסור להשתמש ב-`acceptProposedAction()`, ב-`accept()` בלי קביעת action, וב-`TargetMoveAction`.
- assert לפני accept ב-dropEvent.
- unit test עם `QDropEvent` סינתטי שבו Shift לחוץ.
- מנוע ההמרה לא מזיז, לא מוחק ולא דורס קבצי קלט. תמיד נוצר קובץ חדש.

### 3.4 זיהוי תחילת הגרירה

| גישה | יתרונות | חסרונות | המלצה |
|---|---|---|---|
| **Raw Input** (`RegisterRawInputDevices` + ‏`RIDEV_INPUTSINK`) | ‏Microsoft עצמם ממליצים עליו במקום LL hook. אין timeout ואין הסרה שקטה. אסינכרוני, כך שלא מאט את הקלט במערכת. ‏`WM_INPUT` מגיע ל-thread של Qt דרך `QAbstractNativeEventFilter` ✅ | נתוני עכבר יחסיים (את המיקום קוראים ב-`GetCursorPos`). מותר רק רישום אחד לכל סוג התקן בתהליך (Qt לא רושם) ✅ | **ראשי**, בכפוף ל-spike |
| **WH_MOUSE_LL** | פשוט, מוכר, בלי DLL ובלי injection ✅ | callback איטי מ-`LowLevelHooksTimeout` (עד 1000ms) גורם להסרה **שקטה** של ה-hook ✅. בפייתון: GIL, ‏GC ו-threads כבדים מאטים את כל העכבר במערכת 🔶 | **חלופה.** ב-thread ייעודי עם message loop, ‏callback מינימלי, ו-watchdog שמתקין מחדש |
| **WH_KEYBOARD_LL** | | זה הדפוס הקלאסי של keylogger, ומעורר heuristics של אנטי-וירוס 🔶 | **לא להשתמש.** את מצב המקש קוראים ב-`GetAsyncKeyState` ברגע שהגרירה חוצה את הסף |
| **Polling** (`GetAsyncKeyState(VK_LBUTTON/VK_SHIFT)` + ‏`GetCursorPos` ב-QTimer) | בלי hooks בכלל, ולכן ידידותי לאנטי-וירוס. זו הגישה של tangerine-windows ו-ZestDrop ✅ | פשרה בין זמן תגובה לסוללה. אפשר לפספס לחיצות קצרות 🔶 | **מועמד שלישי** ל-spike |

**היוריסטיקות לזיהוי "גרירת קובץ" ולא גרירת חלון או סימון טקסט:**

- **סף גרירה:** ‏`SM_CXDRAG`/`SM_CYDRAG` (4×4 במחשב הזה ✅). ב-per-monitor-v2 משתמשים ב-`GetSystemMetricsForDpi`.
- **סינון לפי חלון המקור** ✅ (נבדק מקומית על build 26200): ב-mouse-down עושים `WindowFromPoint`, עוברים על שרשרת ההורים, וקוראים `GetClassName`.
  - **לקבל:** שרשרת שכוללת `SHELLDLL_DefView`, כלומר רשימת הקבצים ב-Explorer ושולחן העבודה (`Progman`), או `NamespaceTreeControl`, כלומר עץ הניווט.
  - **לדחות:**
    - `TITLE_BAR_SCAFFOLDING_WINDOW_CLASS`: גרירת לשוניות או שורת כותרת.
    - `Microsoft.UI.Content.DesktopChildSiteBridge`: שורת כתובת WinUI.
  - לא להסתמך על `WorkerW`.
- **אישור סופי:** ‏DragEnter עם `hasUrls()` על ה-overlay. עד אז הפרוסות מוצגות במצב "לא חמוש".
- **אות משני אפשרי:** ‏SetWinEventHook שמזהה יצירה של חלון בשם `SysDragImage`. ❔ זה ייבדק ב-spike.

### 3.5 חלופות שנבדקו ונפסלו

| חלופה | למה לא |
|---|---|
| **UI Automation** (אירועי drag) | בבדיקות קהילה Explorer לא שולח אירועי drag. בנוסף איטי ושביר בין תהליכים |
| **WinEvents** (`EVENT_OBJECT_DRAGSTART`, ‏`EVENT_SYSTEM_DRAGDROPSTART`) | האפליקציה צריכה לשלוח אותם בעצמה ("the system does not send it") ✅, ולפי בדיקות קהילה Explorer לא שולח |
| **Shell extension** (DragDropHandler / IShellExtInit) | נטען בתוך explorer.exe ודורש C++. רץ ברגע השחרור ולא בתחילת הגרירה |
| **Hook ל-DoDragDrop דרך injection** | דורש DLL נייטיבי, מדליק את ה-EDR ושביר בין עדכוני Explorer |
| **הקבצים המסומנים כרגע** (Shell.Application → IShellWindows → SelectedItems) | עם הלשוניות של Win11 אין דרך מתועדת לזהות את הלשונית הפעילה. מתאים רק לפיצ'ר עתידי של "המר את הבחירה בקיצור מקלדת" |
| **Polling** (cursor / `SysDragImage`) | מתאים רק כאות אישור, לא כמנגנון ראשי |

### 3.6 חסמים ופתרונות

**הרשאות אדמין:**
- **לא צריך אדמין, ואסור לרוץ כ-elevated.**
- UIPI חוסם drag-and-drop מ-Explorer רגיל לחלון elevated, ו-`ChangeWindowMessageFilterEx` לא עוזר ל-OLE. ✅
- כשחלון elevated בחזית, ‏`GetAsyncKeyState` מחזיר 0. ✅
- **פתרון:**
  - האפליקציה רצה ב-medium integrity, בלי uiAccess.
  - בבדיקה בעלייה, אם התהליך elevated, מציגים אזהרה.
  - ה-installer צריך להפעיל את האפליקציה כמשתמש המקורי (`runasoriginaluser` ב-Inno Setup) 🔶. בלי זה האפליקציה תרוץ elevated וה-drops ייכשלו בשקט.

**חלון ה-overlay** ✅ (מיפוי ה-flags מ-qwindowswindow.cpp):
- **flags:** `Qt.Tool | FramelessWindowHint | WindowStaysOnTopHint | WindowDoesNotAcceptFocus`, ‏`WA_TranslucentBackground`, ‏`WA_ShowWithoutActivating`. יוצא WS_EX_TOOLWINDOW, ‏WS_EX_NOACTIVATE ו-layered window.
- **hit-testing:** פיקסלים עם alpha 0 "שקופים" לעכבר ול-drop. ✅
  - לכן כל הדיסקית, כולל הרווחים בין הפרוסות והמרכז, נצבעת ב-**alpha ≥ 1**, ומחוץ לדיסקית alpha 0.
- **אסור:**
  - `WindowTransparentForInput` (מוסיף WS_EX_TRANSPARENT, ואז DragEnter לא יגיע לעולם) ✅
  - `WA_TransparentForMouseEvents`
  - להפעיל (activate) את החלון: Esc חייב להגיע ללולאת הגרירה של Explorer 🔶
- **יוצרים את החלון הנייטיבי מראש** (`winId()`) בעלייה, כך שה-drop target כבר רשום. בזמן ההפעלה רק מזיזים ומציגים.

**DPI וריבוי מסכים:**
- Qt 6.5 ומעלה הוא Per-Monitor-v2 כברירת מחדל. ✅
- ה-hook ו-WindowFromPoint עובדים בפיקסלים פיזיים, ו-Qt בפיקסלים לוגיים.
- **לכן:**
  - ממקמים לפי `QCursor.pos()` ו-`screenAt()`.
  - מגבילים לגבולות `availableGeometry()`, ולא נותנים לחלון לחצות שני מסכים.
  - הקואורדינטות יכולות להיות שליליות.

**אנטי-וירוס, SmartScreen וחתימה:**
- בנייה ב-PyInstaller שכוללת global hook נוטה ל-false positives. ❔
  - **פתרון:** ‏onedir (לא onefile), בלי UPX, עם version resource וחתימה. אם צריך, לדווח ל-Microsoft. ‏Nuitka כחלופה.
- **SmartScreen:** גם EV כבר לא מעניק מוניטין מיידי. ❔ (מקור משני)
- **אפשרויות חתימה:**
  - **SignPath Foundation:** חינם לקוד פתוח. דורש רישיון OSI, בנייה אוטומטית ב-CI, ומדיניות חתימה פומבית. ✅
  - **Microsoft Artifact Signing** (לשעבר Azure Trusted Signing): למפתחים יחידים רק בארה"ב ובקנדה. ✅
  - **Microsoft Store:** רישום חינם ליחידים מספטמבר 2025. ✅ ‏Microsoft חותמים על ה-MSIX, וזה גם נותן package identity, שנדרש לתפריט ההקשר העליון. האם אפליקציה full-trust עם hook גלובלי עוברת את בדיקת ה-Store? ❔

### 3.7 ייחודיות Windows 11

- **Explorer עם לשוניות:**
  - שרשרת המחלקות: `CabinetWClass › ShellTabWindowClass › DUIViewWndClassName › DirectUIHWND › CtrlNotifySink › SHELLDLL_DefView › DirectUIHWND`. ✅
  - הלשוניות לא מפריעות לזיהוי (A), אבל מסבכות כל פתרון שמבוסס על "הקבצים המסומנים".
- **Shift לפני הלחיצה** ב-Explorer מסמן טווח קבצים 🔶, כלומר נגרר טווח שלם במקום קובץ אחד.
  - **לכן:** את המקש בודקים *כשהגרירה חוצה את הסף*, ומעודדים ללחוץ עליו אחרי תחילת הגרירה.
  - חמש לחיצות Shift מקפיצות את חלון Sticky Keys. 🔶
- **מגש הגרירה:** הוסר ב-KB5121003. כדאי לוודא ב-build 26200 שהוא לא מופיע, ולהתרחק ממרכז הקצה העליון של המסך.
- **תפריט הקשר עליון:** דורש IExplorerCommand וזהות חבילה, לכן נדחה לשלב מאוחר (נקודת כניסה משנית).

### 3.8 ארכיטקטורה מומלצת

```
 בעלייה: בדיקה שלא elevated → יצירת overlay מוסתר + winId() → רישום Raw Input (או LL hook + watchdog)

 [Explorer / Desktop]                         [האפליקציה, medium integrity]
  mouse-down על קובץ ─────► Raw Input ──► שמירת נקודת התחלה + שרשרת מחלקות
  תזוזה מעבר לסף ─────────► Raw Input ──► Shift לחוץ? מקור מורשה?
                                              │ queued Qt signal (בלי שום עבודה ב-callback)
                                              ▼
                                  overlay.move(cursor) + show, בלי activate, מצב "לא חמוש"
  לולאת OLE DoDragDrop ──WindowFromPoint──► IDropTarget של ה-overlay (Qt)
                                              │ DragEnter/Move: hasUrls → setDropAction(Copy) → accept
                                              │ → "חמוש", הדגשת הפרוסה שמתחת לסמן
                                              │ Drop: Copy + assert → העתקת נתיבים + מזהה פרוסה → return מיידי
                                              ▼
                                  תור משימות → subprocess workers (Pillow / FFmpeg CLI)
                                              │ קובץ חדש ליד המקור; המקור לא נוגעים בו
                                              ▼
                                  toast הצלחה (+ "הצג בתיקייה")
  mouse-up / Esc / timeout ──────────────► הסתרת ה-overlay (ביטול = לא קורה כלום)
```

### 3.9 סיכונים פתוחים ו-spike מוצע

> **עדכון:** ה-spike הורץ ב-19.10.2026.
> - R1, ‏R3 ו-R5 נסגרו.
> - R2: ההגנה (Copy כפוי) עובדת. המחיקה עצמה על ידי Explorer לא הורצה.
> - R4 נסגר חלקית: לא נבדקו חלון elevated ועומס GIL.
> - R6 תואם את הצפי. 🔶
> - R7 הופרך.
>
> התוצאות ב-[phase-1b-spike-results.md](phase-1b-spike-results.md).

את הסיכונים האלה רק ניסוי אמיתי יכריע (המחשב הזה: Windows 11 25H2, build 26200.9711):

| # | סיכון | מה מודדים |
|---|---|---|
| 1 | **DragEnter על חלון שמוצג באמצע גרירה** | האם מגיע, תוך כמה זמן, ומה קורה כשהסמן עומד במקום. מקורות לבדיקה: Explorer, שולחן העבודה, Chrome, ‏VS Code |
| 2 | **בטיחות** | ש-Shift+drop עם כפיית Copy משאיר את המקור. מומלץ לבדוק גם ש-`accept()` רגיל מוחק אותו, על קובץ דמה בלבד |
| 3 | **Hit-testing בגרירה אמיתית** | ש-alpha ≥ 1 נתפס כ-target ו-alpha 0 שקוף |
| 4 | **Raw Input מול LL hook** | זמני תגובה תחת עומס, והתנהגות כשחלון elevated בחזית |
| 5 | **WinEvents** | האם `SysDragImage` נוצר בכל גרירה, והאם Explorer שולח DRAGSTART בכלל |
| 6 | **Shift אחרי תחילת הגרירה** | תופעות לוואי בבחירה, והאם משוב ה-"Move" של Explorer מבלבל לפני שה-overlay מופיע |
| 7 | **הטענה של tangerine-windows** (§3.1) | האם `OleGetClipboard` בזמן גרירה מ-Explorer מחזיר את הקבצים הנגררים עם `InShellDragLoop`, באיזה build, והאם יש false positives מ-clipboard ישן |

**הצעה:** ‏spike זמני של כ-150 שורות, ב-scratchpad ולא בתיקיית הפרויקט.
- **מה הוא כולל:** ‏overlay של PySide6, זיהוי ב-Raw Input וב-LL hook, ולוג של DragEnter עם חותמות זמן.
- **אתה מבצע את הגרירות בפועל** (אני לא יכול לגרור פיזית), ואני מנתח את הלוג.
- **זה לא קוד פרודקשן:** הוא נזרק ורק מכריע את סיכונים 1–7 לפני שננעל ארכיטקטורה בשלב 4.

---

## 4. Tech stack בסיסי

הגרסאות נבדקו ב-PyPI ב-19.10.2026.

| שכבה | בחירה מומלצת | חלופה | רישיון | הערה |
|---|---|---|---|---|
| Runtime | **Python 3.12** (מותקן 3.12.10) | 3.13 | PSF | |
| GUI | **PySide6 6.12.0** | PyQt6 6.11.0 | LGPLv3 / GPLv3 | PyQt6 מחייב את כל הפרויקט להיות GPL. PySide6 כמעט drop-in ומשאיר חופש רישוי (החלטה 2) |
| Win32 interop | **ctypes** (stdlib) | pywin32 312, ‏comtypes 1.4.17 | | ‏pynput 1.8.2 לא מומלץ: עטיפה כללית סביב LL hook, וחסרה לנו שליטה ב-Raw Input |
| זיהוי קלט | **Raw Input** + ‏`QAbstractNativeEventFilter` | ‏WH_MOUSE_LL ב-thread ייעודי | | ה-spike יכריע |
| Drop target | **Qt נייטיבי** (`QWindowsOleDropTarget`) | COM ישיר | | עם כפיית Copy (§3.3) |
| תמונות | **Pillow 13.0.0** + ‏**pillow-heif 1.8.1** | pillow-avif-plugin 1.6.0 (אם AVIF לא נתמך בבנייה) | MIT-CMU / BSD-3 | **עדכון:** אומת מקומית ש-Pillow 13 תומך ב-AVIF בעצמו, ולכן ה-plugin מיותר. |
| אודיו/וידאו | **FFmpeg CLI** ב-subprocess, יורד לפי דרישה | static-ffmpeg 3.0 / imageio-ffmpeg 0.6.0 | LGPL או GPL לפי הבנייה | הורדה לפי דרישה מקטינה את ה-installer (השיבוטים 80–262MB) ומפרידה את רישוי FFmpeg מהפרויקט |
| PDF | **pypdf 6.21.1** (מיזוג ופיצול) | pypdfium2 לרינדור PDF→תמונה ❔ לאימות | BSD-3 | **לא PyMuPDF** (AGPL) |
| מסמכי Office | **LibreOffice headless** (חיצוני, אופציונלי, מזוהה אם מותקן) | pandoc | MPL | לא ב-MVP |
| Workers | **multiprocessing / subprocess** | | | לא threads, בגלל ה-GIL והשפעתו על הקלט |
| התראות | **toast מצויר ב-Qt** + ‏`QSystemTrayIcon` | windows-toasts 1.3.1, ‏win11toast 0.36.3 | MIT | ל-toast נייטיבי מאפליקציה לא ארוזה צריך AppUserModelID רשום 🔶 |
| הגדרות | **TOML** (`tomllib`) + ‏**platformdirs 4.13.4** | pydantic 2.14 לוולידציה | MIT | |
| אריזה | **PyInstaller 6.22.3** ‏onedir, בלי UPX, + Inno Setup | Nuitka 4.3.1 (ב-PyPI מופיע AGPLv3, לבדוק השלכות), ‏MSIX ל-Store | GPL עם exception | |
| חתימה | **SignPath Foundation** | Microsoft Store | | |
| הפעלה עם Windows | **HKCU\…\CurrentVersion\Run** | קיצור ב-Startup | | בלי אדמין |
| בדיקות | **pytest** + ‏pytest-qt | | | כולל test חובה ל-Shift→Copy |

---

## 5. החלטות שנדרשות ממך לפני שלב 2

1. **מיצוב, לאור Filee.**
   - **(א) מומלץ:** פרויקט עצמאי עם בידול ברור:
     - "safety-first": הבטחה של לעולם לא Move ולעולם לא דריסה, וביטול שלא עושה כלום
     - מקשים שאפשר להגדיר
     - **מערכת הרחבות בפייתון** (ממיר חדש בכמה עשרות שורות)
     - בנייה חתומה
     - installer קטן
     - בעתיד: מקורות מעבר ל-Explorer

     את Filee ו-tangerine-windows (שניהם MIT) לומדים כרפרנס.
   - **(ב)** לתרום ל-Filee. זה C#, כלומר מחוץ ל-stack שהגדרת.
   - **(ג)** fork ל-tangerine-windows (אותו stack). לא מומלץ: 0 כוכבים, לא נבדק ידנית ב-Explorer, והשם בעייתי.
2. **ספריית Qt ורישיון הפרויקט.** זו המלצה לשנות את מה שבחרת ב-brief.
   - **מומלץ:** ‏PySide6 עם רישיון MIT או Apache-2.0.
   - **הבחירה המקורית שלך:** ‏PyQt6 עם GPLv3. גם זה מסלול קוד פתוח תקין; מוותרים רק על רישוי מתירני.
3. **מקש ההפעלה.**
   - **מומלץ:** ‏Shift כברירת מחדל, כמו במקור. הוא נבדק כשהגרירה חוצה את הסף, ואפשר לשנות אותו בהגדרות.
   - הבטיחות מגיעה מכפיית Copy, לא מבחירת המקש.
   - Ctrl יציב יותר אם ה-overlay לא נפתח (התוצאה היא עותק, לא העברה), אבל זה כבר הטריגר של Filee.
4. **Spike:** להריץ את ה-spike הזמני (§3.9) לפני שלב 2, או לדחות אותו עד לפני שלב 4.
5. **שם לפרויקט:** לא "Tangerine", בגלל סיכון של סימן מסחרי. אפשר להחליט כבר עכשיו או בשלב 2.
6. **אופציונלי, לשלב 3:** אישור להוריד את 3 סרטוני הדמו של Tangerine (קבצי MP4 קצרים מ-video.twimg.com) כדי לחלץ פריימים של הגלגלת.

---

## 6. מקורות עיקריים

**Tangerine:**
- [App Store](https://apps.apple.com/us/app/tangerine-file-converter/id6813034065?mt=12)
- [iTunes API](https://itunes.apple.com/lookup?id=6813034065&country=us)
- [פוסט ההשקה ב-X](https://x.com/th2049/status/2097015553508725184)
- [Product Hunt](https://www.producthunt.com/products/tangerine-zero-click-file-converter)
- [MacGeneration](https://www.macg.co/logiciels/2026/10/tangerine-un-convertisseur-de-fichiers-toujours-portee-de-main-sur-mac-311381)

**מתחרים:**
- [Filee](https://github.com/KnifeLemon/Filee)
- [tangerine-windows](https://github.com/CristianO2601/tangerine-windows)
- [ZestDrop](https://github.com/Maxaccurate/ZestDrop)
- [KiwiConvert](https://github.com/jherobred/KiwiConvert)
- [Convertino](https://github.com/sanyamgoelx/convertino)
- [File Converter](https://github.com/Tichau/FileConverter) (ו-[issue ‏#598](https://github.com/Tichau/FileConverter/issues/598))
- [Kando](https://kando.menu/)
- [PowerToys Image Resizer](https://learn.microsoft.com/en-us/windows/powertoys/image-resizer)

**Windows:**
- [KB5058499: מגש הגרירה נוסף](https://support.microsoft.com/en-us/topic/may-28-2025-kb5058499-os-build-26100-4202-preview-d4c2f1ee-8138-4038-b705-546945076f92)
- [KB5121003: מגש הגרירה הוסר](https://support.microsoft.com/en-us/servicing/os/windows-11/2026/08/kb5121003-windows-11-24h2-25h2-security-update)
- [תפריט ההקשר של Win11](https://blogs.windows.com/windowsdeveloper/2021/07/19/extending-the-context-menu-and-share-dialog-in-windows-11/)

**טכני:**
- [DoDragDrop](https://learn.microsoft.com/en-us/windows/win32/api/ole2/nf-ole2-dodragdrop)
- [IDropTarget::DragOver](https://learn.microsoft.com/en-us/windows/win32/api/oleidl/nf-oleidl-idroptarget-dragover)
- [Shell Data Scenarios](https://learn.microsoft.com/en-us/windows/win32/shell/datascenarios)
- [LowLevelMouseProc](https://learn.microsoft.com/en-us/windows/win32/winmsg/lowlevelmouseproc)
- [RAWINPUTDEVICE](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-rawinputdevice)
- [Window Features: layered hit-testing](https://learn.microsoft.com/en-us/windows/win32/winmsg/window-features)
- [Raymond Chen על WindowFromPoint](https://devblogs.microsoft.com/oldnewthing/20110218-00/?p=11453)
- [UIPI וגרירה](https://learn.microsoft.com/en-us/archive/blogs/patricka/q-why-doesnt-drag-and-drop-work-when-my-application-is-running-elevated-a-mandatory-integrity-control-and-uipi)
- [Event Constants](https://learn.microsoft.com/en-us/windows/win32/winauto/event-constants)
- [Qt Windows platform plugin](https://github.com/qt/qtbase/tree/dev/src/plugins/platforms/windows)
- [התיקון ב-Avidemux](https://github.com/mean00/avidemux2/commit/ac6f21c)

**חתימה:**
- [SignPath Foundation](https://signpath.org/terms)
- [Artifact Signing](https://learn.microsoft.com/azure/artifact-signing/quickstart)
- [Store: רישום חינם](https://blogs.windows.com/windowsdeveloper/2025/09/10/free-developer-registration-for-individual-developers-on-microsoft-store/)

---

## 7. החלטות שאושרו (19.10.2026)

| # | נושא | החלטה |
|---|---|---|
| 1 | מיצוב | **(א):** פרויקט עצמאי שמתבדל ב-safety-first, בטריגר שאפשר להגדיר, במערכת הרחבות בפייתון ובבנייה חתומה. ‏Filee ו-tangerine-windows משמשים כרפרנס בלבד. |
| 2 | ספריית Qt ורישיון | **PySide6 עם רישיון MIT**, במקום PyQt6. |
| 3 | מקש הפעלה | **Shift כברירת מחדל**, נבדק כשהגרירה חוצה את הסף, וניתן לשינוי בהגדרות. כפיית CopyAction היא חובה. |
| 4 | Spike | **רץ לפני שלב 2**, ב-scratchpad, כקוד זמני שנזרק בסוף. |
| 5 | שם הפרויקט | פתוח, ייקבע בשלב 2. |
| 6 | סרטוני דמו | פתוח, לשלב 3. |
