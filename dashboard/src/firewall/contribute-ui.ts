import type { FirewallLocale } from "./locale";

type ContributeUi = {
  close: string; contribute: string; title: string; intro: string; contributors: string; guides: string;
  steps: [string, string, string, string]; fill: string; ci: string;
  links: [string, string, string, string, string, string, string, string];
  notes: [string, string, string, string, string, string, string, string];
};

export const contributeUi: Record<FirewallLocale, ContributeUi> = {
  en: {
    close: "Close", contribute: "Contribute", title: "Add your company to the book.", intro: "Every design here arrived as a pull request. Yours can too.", contributors: "Contributors", guides: "Guides, templates and standards",
    steps: ["Copy", "Fill", "Validate", "Open a PR"], fill: "company.json + README.md. Every rule gets a reason.", ci: "CI revalidates and rebuilds the catalog.",
    links: ["CONTRIBUTING", "CONTRIBUTORS", "Standards", "Schema", "Knowledge notes", "PR template", "Issue templates", "Code of conduct"],
    notes: ["How we work, branch and commit", "Everyone who added a company", "Rules of a good submission, checklist", "Field-by-field company.json contract", "Segmentation, rule order, products, monitoring", "What every pull request must answer", "Bug · docs · feature request", "Be kind, be specific"]
  },
  tr: {
    close: "Kapat", contribute: "Katkıda bulun", title: "Şirketini kataloğa ekle.", intro: "Buradaki her tasarım bir pull request ile eklendi. Seninki de eklenebilir.", contributors: "Katkıda bulunanlar", guides: "Rehberler, şablonlar ve standartlar",
    steps: ["Kopyala", "Doldur", "Doğrula", "PR aç"], fill: "company.json + README.md. Her kuralın bir gerekçesi olmalı.", ci: "CI doğrular ve kataloğu yeniden oluşturur.",
    links: ["Katkı rehberi", "Katkıda bulunanlar", "Standartlar", "Şema", "Bilgi notları", "PR şablonu", "İş şablonları", "Davranış kuralları"],
    notes: ["Çalışma, dal ve commit düzeni", "Şirket ekleyen herkes", "İyi bir katkı için kontrol listesi", "company.json alanlarının tanımı", "Bölümlendirme, kural sırası, ürünler, izleme", "Her PR'ın yanıtlaması gerekenler", "Hata, belge ve özellik isteği", "Saygılı ve açık iletişim"]
  },
  de: {
    close: "Schließen", contribute: "Beitragen", title: "Füge dein Unternehmen zum Katalog hinzu.", intro: "Jeder Entwurf wurde per Pull Request hinzugefügt. Deiner kann der nächste sein.", contributors: "Mitwirkende", guides: "Anleitungen, Vorlagen und Standards",
    steps: ["Kopieren", "Ausfüllen", "Prüfen", "PR öffnen"], fill: "company.json + README.md. Jede Regel braucht eine Begründung.", ci: "CI prüft erneut und erstellt den Katalog neu.",
    links: ["Beitragsleitfaden", "Mitwirkende", "Standards", "Schema", "Wissensnotizen", "PR-Vorlage", "Issue-Vorlagen", "Verhaltensregeln"],
    notes: ["Arbeitsweise, Branches und Commits", "Alle, die ein Unternehmen hinzugefügt haben", "Checkliste für gute Beiträge", "Felder und Vertrag von company.json", "Segmentierung, Regelreihenfolge, Produkte, Überwachung", "Fragen für jeden Pull Request", "Fehler · Dokumentation · Funktionswunsch", "Freundlich und konkret bleiben"]
  },
  fr: {
    close: "Fermer", contribute: "Contribuer", title: "Ajoutez votre entreprise au catalogue.", intro: "Chaque conception a été ajoutée par pull request. La vôtre peut l’être aussi.", contributors: "Contributeurs", guides: "Guides, modèles et normes",
    steps: ["Copier", "Remplir", "Valider", "Ouvrir une PR"], fill: "company.json + README.md. Chaque règle doit être justifiée.", ci: "La CI valide à nouveau et reconstruit le catalogue.",
    links: ["Guide de contribution", "Contributeurs", "Normes", "Schéma", "Notes techniques", "Modèle de PR", "Modèles de ticket", "Code de conduite"],
    notes: ["Méthode de travail, branches et commits", "Toutes les personnes ayant ajouté une entreprise", "Liste de contrôle pour contribuer", "Contrat champ par champ de company.json", "Segmentation, ordre des règles, produits, surveillance", "Questions auxquelles chaque PR doit répondre", "Bogue · documentation · demande de fonctionnalité", "Restez aimable et précis"]
  },
  es: {
    close: "Cerrar", contribute: "Contribuir", title: "Añade tu empresa al catálogo.", intro: "Todos los diseños se añadieron mediante una pull request. El tuyo también puede estar aquí.", contributors: "Colaboradores", guides: "Guías, plantillas y estándares",
    steps: ["Copiar", "Completar", "Validar", "Abrir una PR"], fill: "company.json + README.md. Cada regla necesita una justificación.", ci: "La CI vuelve a validar y reconstruye el catálogo.",
    links: ["Guía de contribución", "Colaboradores", "Estándares", "Esquema", "Notas de conocimiento", "Plantilla de PR", "Plantillas de incidencias", "Código de conducta"],
    notes: ["Cómo trabajamos, ramas y commits", "Quienes añadieron una empresa", "Lista para una buena contribución", "Contrato campo por campo de company.json", "Segmentación, orden de reglas, productos, supervisión", "Qué debe responder cada PR", "Error · documentación · nueva función", "Sé amable y concreto"]
  },
  it: {
    close: "Chiudi", contribute: "Contribuisci", title: "Aggiungi la tua azienda al catalogo.", intro: "Ogni progetto è stato aggiunto tramite pull request. Anche il tuo può esserlo.", contributors: "Collaboratori", guides: "Guide, modelli e standard",
    steps: ["Copia", "Compila", "Convalida", "Apri una PR"], fill: "company.json + README.md. Ogni regola richiede una motivazione.", ci: "La CI convalida di nuovo e ricostruisce il catalogo.",
    links: ["Guida ai contributi", "Collaboratori", "Standard", "Schema", "Note tecniche", "Modello PR", "Modelli di segnalazione", "Codice di condotta"],
    notes: ["Come lavoriamo, branch e commit", "Chi ha aggiunto un’azienda", "Lista di controllo per un buon contributo", "Contratto campo per campo di company.json", "Segmentazione, ordine delle regole, prodotti, monitoraggio", "Domande a cui ogni PR deve rispondere", "Bug · documentazione · richiesta di funzionalità", "Sii gentile e preciso"]
  },
  fa: {
    close: "بستن", contribute: "مشارکت", title: "شرکت خود را به فهرست اضافه کنید.", intro: "هر طرح اینجا با یک درخواست ادغام اضافه شده است. طرح شما هم می‌تواند اضافه شود.", contributors: "مشارکت‌کنندگان", guides: "راهنماها، قالب‌ها و استانداردها",
    steps: ["کپی", "تکمیل", "اعتبارسنجی", "باز کردن PR"], fill: "company.json + README.md. هر قانون باید دلیل داشته باشد.", ci: "سامانه CI دوباره بررسی می‌کند و فهرست را می‌سازد.",
    links: ["راهنمای مشارکت", "مشارکت‌کنندگان", "استانداردها", "طرحواره", "یادداشت‌های آموزشی", "قالب PR", "قالب‌های مسئله", "آیین رفتار"],
    notes: ["روش کار، شاخه‌ها و ثبت تغییرات", "همه کسانی که شرکتی اضافه کرده‌اند", "فهرست بررسی مشارکت خوب", "تعریف تک‌تک فیلدهای company.json", "بخش‌بندی، ترتیب قوانین، محصولات، پایش", "پرسش‌های لازم برای هر PR", "اشکال · مستندات · درخواست قابلیت", "محترمانه و دقیق باشید"]
  },
  ar: {
    close: "إغلاق", contribute: "المساهمة", title: "أضف شركتك إلى الفهرس.", intro: "أُضيف كل تصميم هنا عبر طلب سحب. يمكن إضافة تصميمك أيضًا.", contributors: "المساهمون", guides: "الأدلة والقوالب والمعايير",
    steps: ["نسخ", "ملء", "تحقق", "فتح PR"], fill: "company.json + README.md. تحتاج كل قاعدة إلى مبرر.", ci: "تتحقق CI مجددًا وتعيد بناء الفهرس.",
    links: ["دليل المساهمة", "المساهمون", "المعايير", "المخطط", "ملاحظات معرفية", "قالب PR", "قوالب المشكلات", "مدونة السلوك"],
    notes: ["أسلوب العمل والفروع وعمليات الحفظ", "كل من أضاف شركة", "قائمة تحقق للمساهمة الجيدة", "تعريف حقول company.json واحدًا واحدًا", "التقسيم وترتيب القواعد والمنتجات والمراقبة", "ما يجب أن يجيب عنه كل طلب سحب", "خطأ · توثيق · طلب ميزة", "كن لطيفًا ومحددًا"]
  }
};
