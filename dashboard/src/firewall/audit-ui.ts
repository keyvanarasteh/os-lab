import type { FirewallLocale } from "./locale";
import type { Category } from "./audit";

type AuditUi = {
  health: string; healthScore: (n: number) => string; severity: string; more: string;
  asked: string; taught: string; impact: string; hideDetails: string; allExamples: (n: number) => string; howFix: string;
  gaps: string; audit: string; nothing: string; summary: (issues: number, total: number) => string;
  checks: (n: number) => string; brief: string; lectures: string; matrix: string; companyWide: string;
  topTen: string; showAll: (n: number) => string; close: string; path: string;
  hackable: string; weak: string; expensive: string;
};

export const auditUi: Record<FirewallLocale, AuditUi> = {
  en: {
    health: "health", healthScore: (n) => `Health score ${n} out of 100`, severity: "Severity", more: "more",
    asked: "Asked in the group", taught: "Taught in class", impact: "Why it hurts", hideDetails: "Hide details", allExamples: (n) => `All ${n} · how to fix`, howFix: "How to fix",
    gaps: "Gaps and missing pieces", audit: "Gap audit", nothing: "Nothing missing", summary: (issues, total) => `${issues} issues across ${total} gaps`,
    checks: (n) => `Checked against what was asked in the BGT207 group and taught in the recordings: ${n} checks run. Every affected branch, firewall and rule is listed, worst first.`,
    brief: "from the brief", lectures: "from lectures", matrix: "Which branch each gap touches", companyWide: "company-wide",
    topTen: "Show the top 10", showAll: (n) => `Show all ${n} gaps`, close: "Close", path: "Path",
    hackable: "Hackable", weak: "Weak", expensive: "Expensive"
  },
  tr: {
    health: "sağlık", healthScore: (n) => `Sağlık puanı 100 üzerinden ${n}`, severity: "Önem derecesi", more: "diğer",
    asked: "Grupta soruldu", taught: "Derste anlatıldı", impact: "Etkisini gör", hideDetails: "Ayrıntıları gizle", allExamples: (n) => `Tüm ${n} örnek · çözüm`, howFix: "Nasıl düzeltilir?",
    gaps: "Eksikler ve açıklar", audit: "Açık denetimi", nothing: "Eksik bulunmadı", summary: (issues, total) => `${total} açıkta ${issues} sorun`,
    checks: (n) => `BGT207 grubunda sorulanlar ve ders kayıtlarında anlatılanlar doğrultusunda ${n} kontrol yapıldı. Etkilenen tüm şubeler, güvenlik duvarları ve kurallar önem sırasına göre listelenir.`,
    brief: "ödevden", lectures: "derslerden", matrix: "Her açığın etkilediği şubeler", companyWide: "şirket genelinde",
    topTen: "İlk 10'u göster", showAll: (n) => `${n} açığın tümünü göster`, close: "Kapat", path: "Yol",
    hackable: "Saldırıya açık", weak: "Zayıf", expensive: "Maliyetli"
  },
  de: {
    health: "Sicherheit", healthScore: (n) => `Sicherheitswert ${n} von 100`, severity: "Schweregrad", more: "weitere",
    asked: "In der Gruppe gefragt", taught: "Im Unterricht behandelt", impact: "Auswirkung ansehen", hideDetails: "Details ausblenden", allExamples: (n) => `Alle ${n} · Behebung`, howFix: "Wie beheben?",
    gaps: "Lücken und fehlende Elemente", audit: "Lückenprüfung", nothing: "Keine Lücken gefunden", summary: (issues, total) => `${issues} Probleme in ${total} Lücken`,
    checks: (n) => `${n} Prüfungen anhand der Fragen aus der BGT207-Gruppe und der Unterrichtsaufzeichnungen durchgeführt. Alle betroffenen Standorte, Firewalls und Regeln sind nach Schwere sortiert.`,
    brief: "aus der Aufgabenstellung", lectures: "aus dem Unterricht", matrix: "Von jeder Lücke betroffene Standorte", companyWide: "unternehmensweit",
    topTen: "Die ersten 10 anzeigen", showAll: (n) => `Alle ${n} Lücken anzeigen`, close: "Schließen", path: "Pfad",
    hackable: "Angreifbar", weak: "Schwach", expensive: "Kostspielig"
  },
  fr: {
    health: "santé", healthScore: (n) => `Score de santé : ${n} sur 100`, severity: "Gravité", more: "autres",
    asked: "Demandé dans le groupe", taught: "Vu en cours", impact: "Voir l’impact", hideDetails: "Masquer les détails", allExamples: (n) => `Les ${n} exemples · solution`, howFix: "Comment corriger ?",
    gaps: "Lacunes et éléments manquants", audit: "Audit des lacunes", nothing: "Aucune lacune trouvée", summary: (issues, total) => `${issues} problèmes dans ${total} lacunes`,
    checks: (n) => `${n} contrôles effectués à partir des questions du groupe BGT207 et des cours enregistrés. Tous les sites, pare-feu et règles concernés sont classés par gravité.`,
    brief: "issus de l’énoncé", lectures: "issus des cours", matrix: "Sites touchés par chaque lacune", companyWide: "dans toute l’entreprise",
    topTen: "Afficher les 10 premiers", showAll: (n) => `Afficher les ${n} lacunes`, close: "Fermer", path: "Chemin",
    hackable: "Exploitable", weak: "Faible", expensive: "Coûteux"
  },
  es: {
    health: "estado", healthScore: (n) => `Puntuación de estado: ${n} de 100`, severity: "Gravedad", more: "más",
    asked: "Preguntado en el grupo", taught: "Explicado en clase", impact: "Ver el impacto", hideDetails: "Ocultar detalles", allExamples: (n) => `Los ${n} ejemplos · solución`, howFix: "¿Cómo corregirlo?",
    gaps: "Carencias y elementos faltantes", audit: "Auditoría de carencias", nothing: "No faltan elementos", summary: (issues, total) => `${issues} problemas en ${total} carencias`,
    checks: (n) => `Se realizaron ${n} comprobaciones según lo preguntado en el grupo BGT207 y lo explicado en las grabaciones. Todas las sedes, cortafuegos y reglas afectadas aparecen por gravedad.`,
    brief: "del enunciado", lectures: "de las clases", matrix: "Sedes afectadas por cada carencia", companyWide: "en toda la empresa",
    topTen: "Mostrar las 10 primeras", showAll: (n) => `Mostrar las ${n} carencias`, close: "Cerrar", path: "Ruta",
    hackable: "Explotable", weak: "Débil", expensive: "Costoso"
  },
  it: {
    health: "stato", healthScore: (n) => `Punteggio di stato: ${n} su 100`, severity: "Gravità", more: "altri",
    asked: "Chiesto nel gruppo", taught: "Spiegato a lezione", impact: "Vedi l’impatto", hideDetails: "Nascondi dettagli", allExamples: (n) => `Tutti i ${n} esempi · soluzione`, howFix: "Come correggere?",
    gaps: "Lacune ed elementi mancanti", audit: "Verifica delle lacune", nothing: "Nessuna lacuna trovata", summary: (issues, total) => `${issues} problemi in ${total} lacune`,
    checks: (n) => `Eseguiti ${n} controlli in base alle domande del gruppo BGT207 e alle lezioni registrate. Sedi, firewall e regole interessati sono elencati per gravità.`,
    brief: "dalla consegna", lectures: "dalle lezioni", matrix: "Sedi interessate da ogni lacuna", companyWide: "in tutta l’azienda",
    topTen: "Mostra le prime 10", showAll: (n) => `Mostra tutte le ${n} lacune`, close: "Chiudi", path: "Percorso",
    hackable: "Attaccabile", weak: "Debole", expensive: "Costoso"
  },
  fa: {
    health: "سلامت", healthScore: (n) => `امتیاز سلامت ${n} از ۱۰۰`, severity: "شدت", more: "مورد دیگر",
    asked: "در گروه پرسیده شد", taught: "در کلاس آموزش داده شد", impact: "مشاهده پیامد", hideDetails: "پنهان کردن جزئیات", allExamples: (n) => `همه ${n} نمونه · راه‌حل`, howFix: "چگونه اصلاح شود؟",
    gaps: "کاستی‌ها و موارد ناقص", audit: "بازبینی کاستی‌ها", nothing: "کاستی پیدا نشد", summary: (issues, total) => `${issues} مشکل در ${total} کاستی`,
    checks: (n) => `${n} بررسی بر پایه پرسش‌های گروه BGT207 و درس‌های ضبط‌شده انجام شد. همه شعبه‌ها، دیواره‌های آتش و قوانین تحت تأثیر به ترتیب شدت فهرست شده‌اند.`,
    brief: "از شرح تمرین", lectures: "از درس‌ها", matrix: "شعبه‌های تحت تأثیر هر کاستی", companyWide: "در سراسر شرکت",
    topTen: "نمایش ۱۰ مورد نخست", showAll: (n) => `نمایش همه ${n} کاستی`, close: "بستن", path: "مسیر",
    hackable: "قابل نفوذ", weak: "ضعیف", expensive: "پرهزینه"
  },
  ar: {
    health: "السلامة", healthScore: (n) => `درجة السلامة ${n} من ١٠٠`, severity: "الخطورة", more: "أخرى",
    asked: "طُرح في المجموعة", taught: "شُرح في الصف", impact: "عرض الأثر", hideDetails: "إخفاء التفاصيل", allExamples: (n) => `كل الأمثلة (${n}) · الحل`, howFix: "كيف تُصلح؟",
    gaps: "الثغرات والعناصر الناقصة", audit: "تدقيق الثغرات", nothing: "لم تُعثر على نواقص", summary: (issues, total) => `${issues} مشكلة ضمن ${total} ثغرة`,
    checks: (n) => `أُجري ${n} فحص استنادًا إلى أسئلة مجموعة BGT207 والدروس المسجلة. تظهر جميع الفروع وجدران الحماية والقواعد المتأثرة مرتبة حسب الخطورة.`,
    brief: "من وصف المهمة", lectures: "من الدروس", matrix: "الفروع المتأثرة بكل ثغرة", companyWide: "على مستوى الشركة",
    topTen: "عرض أول ١٠", showAll: (n) => `عرض جميع الثغرات (${n})`, close: "إغلاق", path: "المسار",
    hackable: "قابل للاختراق", weak: "ضعيف", expensive: "مكلف"
  }
};

const categories: Record<FirewallLocale, Record<Category, string>> = {
  en: { "Web & apps": "Web & apps", Perimeter: "Perimeter", Rules: "Rules", Network: "Network", Operations: "Operations" },
  tr: { "Web & apps": "Web ve uygulamalar", Perimeter: "Çevre", Rules: "Kurallar", Network: "Ağ", Operations: "Operasyonlar" },
  de: { "Web & apps": "Web und Apps", Perimeter: "Perimeter", Rules: "Regeln", Network: "Netzwerk", Operations: "Betrieb" },
  fr: { "Web & apps": "Web et applications", Perimeter: "Périmètre", Rules: "Règles", Network: "Réseau", Operations: "Exploitation" },
  es: { "Web & apps": "Web y aplicaciones", Perimeter: "Perímetro", Rules: "Reglas", Network: "Red", Operations: "Operaciones" },
  it: { "Web & apps": "Web e app", Perimeter: "Perimetro", Rules: "Regole", Network: "Rete", Operations: "Operazioni" },
  fa: { "Web & apps": "وب و برنامه‌ها", Perimeter: "پیرامون", Rules: "قوانین", Network: "شبکه", Operations: "عملیات" },
  ar: { "Web & apps": "الويب والتطبيقات", Perimeter: "المحيط", Rules: "القواعد", Network: "الشبكة", Operations: "العمليات" }
};

export const auditCategory = (category: Category, locale: FirewallLocale) => categories[locale][category];
