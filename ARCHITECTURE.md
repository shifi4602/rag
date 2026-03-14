# Data Extraction Layer — Architecture

## הבעיה שפתרנו

ה-RAG הקיים עבד רק עם **חיפוש סמנטי** (vector search ב-ChromaDB). זה מצוין לשאלות פתוחות, אבל כושל בשלוש סוגי שאלות:

| סוג שאלה | דוגמה | למה סמנטי לא מספיק |
|---|---|---|
| רשימה מלאה | "תן לי את כל ההחלטות" | מחזיר רק top-K, לא מבטיח כיסוי מלא |
| עדכניות | "מה ההנחיה העדכנית ל-RTL?" | מחזיר גם ניסוחים ישנים וגם חדשים |
| מבוסס זמן | "מה שונה בשבוע האחרון?" | אין לו מושג מה הוא "שבוע אחרון" |

---

## הפתרון — 4 קבצים

### 1. `extract.py` — Pipeline חילוץ (מריצים פעם אחת)

```
python extract.py
```

**מה הוא עושה:** קורא כל קובץ `.md` בפרויקט, שולח אותו ל-LLM עם prompt מובנה, ומבקש לחלץ 5 סוגי פריטים:

- `decisions` — החלטות טכניות/ארכיטקטורליות
- `rules` — כללים והנחיות שחובה לעקוב אחריהם
- `warnings` — אזהרות ואזורים רגישים
- `dependencies` — ספריות, שירותים, APIs חיצוניים
- `changes` — עדכונים ושינויים שתועדו

פלט: קובץ `extracted_data.json` עם schema מובנה, timestamps, ומקור לכל פריט.

**Event flow:**
```
StartEvent → discover_files → extract_files (LLM×N) → assemble_store → StopEvent
```

---

### 2. `structured_store.py` — ממשק שאילתות

```python
store = StructuredStore(EXTRACTED_DATA_PATH)
store.get_all("decisions")          # כל ההחלטות
store.get_recent(days=7)            # פריטים מ-7 ימים אחרונים
store.get_by_tags(["auth", "db"])   # לפי תגיות
store.search_text("RTL")            # חיפוש חופשי
```

טוען את ה-JSON לזיכרון ומספק query methods פשוטים — ללא DB חיצוני.

---

### 3. `workflow.py` — הוספת Router + Structured path

**לפני:** pipeline לינארי אחד

**אחרי:** שני נתיבים עם **Router** שמחליט ביניהם:

```
validate_input → route_query (LLM Router)
                      │
              ┌───────┴───────┐
         semantic          structured
              │                  │
           retrieve         execute_structured
           filter           synthesize_structured
           synthesize       → StopEvent
           format_response
           → StopEvent
```

**`route_query`** — שולח את השאלה ל-LLM עם prompt מיוחד. ה-LLM מחזיר JSON כמו:
```json
{"route": "structured", "query_type": "all_type", "item_type": "decisions"}
```

אם ה-store לא קיים או ה-LLM נכשל → fallback אוטומטי לסמנטי.

**`execute_structured`** — מתרגם את החלטת ה-Router לקריאה על ה-store:

```
query_type="all_type"    → store.get_all(item_type)
query_type="recent"      → store.get_recent(days)
query_type="tags"        → store.get_by_tags(tags)
query_type="text_search" → store.search_text(search_text)
```

**`synthesize_structured`** — שולח את הפריטים שנשלפו ל-LLM לניסוח תשובה סופית.

---

### 4. `config.py` + `app.py` — שינויים קטנים

- `config.py`: נוסף `EXTRACTED_DATA_PATH = BASE_DIR / "extracted_data.json"`
- `app.py`: טוען `StructuredStore` בהפעלה, מעביר אותו + `llm` ל-`RAGWorkflow`

---

## סדר הרצה

```powershell
# פעם אחת — בונה את ה-JSON store
python extract.py

# בכל הפעלה — אפליקציית הצ'אט עם ניתוב אוטומטי
python app.py
```
