"""
Generates the four sample policy PDFs in data/documents/.

The PDFs are committed, so you only need this script if you want to change
their content. It needs reportlab (requirements-dev.txt):

    python scripts/make_sample_pdfs.py

The documents belong to a fictional company, Helix Pharma Distribution. Each
page carries a repeated header and a "Page X of Y" footer on purpose: real
internal documents look like this, and removing that boilerplate is one of the
preprocessing steps in app/rag/pdf_preprocessing.py.
"""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "documents"

HEADER = "Helix Pharma Distribution  |  Internal use only"

# Each document: file name, code, title, version, effective date, sections.
# A section is (heading, [paragraphs]); a paragraph starting with "- " is a bullet.
DOCUMENTS = [
    {
        "file": "returns_and_recalls_policy.pdf",
        "code": "HPD-POL-001",
        "title": "Returns, Credit Notes and Product Recalls Policy",
        "version": "3.0",
        "effective": "2026-01-01",
        "sections": [
            ("1. Purpose and scope", [
                "This policy defines when Helix Pharma Distribution (Helix) accepts products back from "
                "customers, how the value of accepted returns is credited, and how product recalls are "
                "handled. It applies to every customer that buys from Helix: pharmacies, hospitals and "
                "clinics. Sales representatives must not promise return conditions that differ from this "
                "policy without written approval from the Commercial Director.",
            ]),
            ("2. Standard returns", [
                "Customers may return unopened and undamaged products within 14 calendar days of the "
                "delivery date. The return request must quote the invoice number and be submitted through "
                "the customer portal or to the customer's account manager.",
                "- Returned products must have at least 6 months of remaining shelf life.",
                "- Original outer packaging and tamper-evident seals must be intact.",
                "- A restocking fee of 5% of the invoice value applies to returns that are not caused by a "
                "Helix error (for example, a customer ordering the wrong strength).",
                "- Returns caused by a Helix error (wrong product, wrong quantity, damage in transit) are "
                "accepted without a restocking fee.",
            ]),
            ("3. Cold-chain products", [
                "Products that must be stored between 2 and 8 °C (vaccines, insulin and biologic medicines) "
                "cannot be returned once the customer has accepted the delivery, because Helix cannot verify "
                "how they were stored after hand-over.",
                "The only exception is a problem that exists at the moment of delivery. If the data logger "
                "shows a temperature excursion, or the product is visibly damaged, the customer must refuse "
                "the delivery, or report the problem within 24 hours of receipt together with a photo of the "
                "data logger reading. Such products are credited at 100% of the invoice value.",
            ]),
            ("4. Near-expiry and expired products", [
                "Products that are within 3 months of their expiry date are accepted for a credit of 50% of "
                "the purchase price, provided they were bought from Helix within the last 12 months. Expired "
                "products are never accepted; the customer must destroy them according to the national "
                "regulations for pharmaceutical waste.",
            ]),
            ("5. Credit notes", [
                "Approved returns are settled with a credit note against future invoices within 10 business "
                "days of Helix receiving the goods. Cash refunds are not given, except when the customer "
                "closes its account with Helix, in which case any remaining credit is paid by bank transfer "
                "within 30 days.",
            ]),
            ("6. Product recalls", [
                "When a manufacturer or the regulator recalls a batch, Helix informs every customer that "
                "received that batch within 24 hours, by phone and by email. Customers must quarantine the "
                "affected stock immediately and return it within 7 calendar days. Recalled products are "
                "credited at 100% of the purchase price and no restocking fee applies. Helix keeps "
                "batch-level delivery records for 5 years so that every recall can be traced to customers.",
            ]),
            ("7. Contacts", [
                "Returns desk: returns@helix-pharma.example, internal extension 214. Recall coordinator: "
                "quality@helix-pharma.example.",
            ]),
        ],
    },
    {
        "file": "cold_chain_sop.pdf",
        "code": "HPD-SOP-002",
        "title": "Cold Chain Storage and Transport - Standard Operating Procedure",
        "version": "1.4",
        "effective": "2026-02-15",
        "sections": [
            ("1. Purpose", [
                "This procedure describes how Helix stores and transports temperature-sensitive medicines so "
                "that they reach customers within their labelled storage conditions. It applies to warehouse "
                "staff, drivers and the Quality Assurance (QA) team.",
            ]),
            ("2. Storage temperature ranges", [
                "- Refrigerated products (vaccines, insulin, biologics): 2 to 8 °C.",
                "- Controlled room temperature products: 15 to 25 °C.",
                "- Frozen products (-20 °C or colder) are not stocked by Helix.",
            ]),
            ("3. Temperature monitoring", [
                "Every cold room, refrigerator and transport box is monitored by a calibrated data logger "
                "that records the temperature every 5 minutes. An alarm is raised when the temperature stays "
                "outside the allowed range for more than 15 minutes. A QA pharmacist reviews the logger data "
                "every working day. Temperature records are kept for 5 years. Data loggers are calibrated "
                "once a year by an accredited laboratory.",
            ]),
            ("4. Handling a temperature excursion", [
                "An excursion is any period during which a product is outside its labelled range.",
                "- If a 2 to 8 °C product was above 8 °C for 30 minutes or less in total, it may stay in "
                "stock. The excursion must be documented in the excursion log.",
                "- If the excursion lasted more than 30 minutes in total, or the product was below 0 °C for "
                "any length of time, the product is quarantined immediately and labelled DO NOT USE.",
                "- QA must be notified within 1 hour of a quarantine. QA decides, using the manufacturer's "
                "stability data, whether the product can be released or must be destroyed. The decision is "
                "made within 2 business days.",
            ]),
            ("5. Transport", [
                "Refrigerated products travel in validated insulated boxes with conditioned ice packs, or in "
                "refrigerated vehicles. The maximum transit time is 8 hours for deliveries inside Tehran and "
                "24 hours for inter-city deliveries; inter-city deliveries of refrigerated products always use "
                "refrigerated vehicles. The driver checks the data logger at hand-over and the customer signs "
                "the delivery note only after seeing that no alarm was raised.",
            ]),
            ("6. Power failure", [
                "Cold rooms are connected to a backup generator that must start within 10 minutes of a power "
                "failure. If a cold room is expected to stay above 8 °C for more than 2 hours, stock is moved "
                "to the backup cold room and the move is recorded.",
            ]),
        ],
    },
    {
        "file": "credit_and_payment_terms.pdf",
        "code": "HPD-FIN-003",
        "title": "Customer Credit and Payment Terms",
        "version": "2.1",
        "effective": "2026-01-01",
        "sections": [
            ("1. Scope", [
                "This document sets the payment terms, credit limits and late-payment rules for all Helix "
                "customers. Finance applies it to every invoice issued from the effective date.",
            ]),
            ("2. Payment terms by customer type", [
                "The payment term is counted in calendar days from the invoice date.",
                "- Pharmacies: 30 days.",
                "- Clinics: 45 days.",
                "- Hospitals: 60 days. Public hospitals may receive 90 days with written approval of the "
                "Chief Financial Officer.",
            ]),
            ("3. Credit limits", [
                "Each customer receives a credit limit when the account is opened, based on three months of "
                "expected purchases. The limit is stored in the customer master data (the credit_limit field) "
                "and reviewed every 6 months. A customer can request a higher limit through its account "
                "manager; increases above 20% need approval from the Finance Manager.",
            ]),
            ("4. Early payment discount", [
                "Customers who pay an invoice in full within 10 days of the invoice date receive a 2% "
                "discount on that invoice, deducted from the next invoice.",
            ]),
            ("5. Late payment", [
                "An invoice that is not paid by the end of its payment term is overdue. Overdue invoices "
                "incur a late-payment fee of 1.5% of the overdue amount for each month, or part of a month, "
                "that the invoice remains unpaid.",
            ]),
            ("6. Credit hold", [
                "An account is placed on credit hold, and new orders are not shipped, when any invoice is "
                "more than 90 days overdue or when the open balance exceeds the credit limit by more than "
                "10%. The hold is lifted as soon as the overdue amount is paid. Orders for recalled-product "
                "replacements are shipped even during a credit hold.",
            ]),
            ("7. Invoice disputes", [
                "Disputes about an invoice must be raised within 15 days of the invoice date. The disputed "
                "amount does not count as overdue while Finance investigates.",
            ]),
        ],
    },
    {
        "file": "adverse_event_reporting.pdf",
        "code": "HPD-PV-004",
        "title": "Adverse Event and Product Quality Complaint Reporting Procedure",
        "version": "1.2",
        "effective": "2026-03-01",
        "sections": [
            ("1. Purpose", [
                "Helix staff regularly hear from pharmacists, doctors and patients about problems with the "
                "medicines we distribute. This procedure makes sure that every such report reaches the "
                "Pharmacovigilance (PV) Officer quickly and with the information needed for evaluation. It "
                "applies to all employees, including sales representatives and drivers.",
            ]),
            ("2. Definitions", [
                "- Adverse event (AE): any unwanted medical occurrence in a patient who used a product we "
                "distribute, whether or not it is thought to be caused by the product.",
                "- Serious adverse event: an AE that results in death, is life-threatening, requires or "
                "prolongs hospitalisation, causes lasting disability, or causes a congenital anomaly.",
                "- Product quality complaint: a report of a possible defect in the product itself, such as "
                "broken tablets, discoloured solution, a missing leaflet or a wrong label.",
            ]),
            ("3. Reporting timelines", [
                "The clock starts when any Helix employee first becomes aware of the event.",
                "- Serious adverse events: report to the PV Officer within 24 hours.",
                "- Non-serious adverse events: report within 5 business days.",
                "- Product quality complaints: report within 2 business days.",
                "The PV Officer forwards every AE report to the marketing authorisation holder within 1 "
                "business day. The marketing authorisation holder is responsible for reporting to the "
                "national regulator.",
            ]),
            ("4. Minimum information", [
                "A report is valid when it contains four elements: an identifiable patient (initials, age or "
                "sex), an identifiable reporter, the suspect product with its batch number, and a description "
                "of the event. Incomplete reports must still be sent on time; the PV Officer follows up for "
                "missing details.",
            ]),
            ("5. How to report", [
                "Send the report by email to pv@helix-pharma.example using form HPD-F-017. Serious adverse "
                "events must also be reported by phone to the 24/7 PV hotline, extension 999.",
            ]),
            ("6. Training", [
                "All employees complete pharmacovigilance training once a year. New employees complete it "
                "within 30 days of joining. Training records are kept by Human Resources.",
            ]),
        ],
    },
]


STYLES = getSampleStyleSheet()
TITLE = ParagraphStyle("title", parent=STYLES["Title"], fontSize=17, leading=21, spaceAfter=6)
META = ParagraphStyle("meta", parent=STYLES["Normal"], fontSize=9, textColor="#555555", spaceAfter=10)
HEADING = ParagraphStyle("h", parent=STYLES["Heading2"], fontSize=12.5, spaceBefore=10, spaceAfter=4)
BODY = ParagraphStyle("body", parent=STYLES["Normal"], fontSize=11, leading=15, spaceAfter=6)
BULLET = ParagraphStyle("bullet", parent=BODY, leftIndent=14, firstLineIndent=-9)


def make_story(doc: dict) -> list:
    """Turn the document dict into reportlab flowables (title, headings, paragraphs)."""
    story = [
        Paragraph(doc["title"], TITLE),
        Paragraph(f"Document {doc['code']}, version {doc['version']}, effective {doc['effective']}.", META),
    ]
    for heading, paragraphs in doc["sections"]:
        story.append(Paragraph(heading, HEADING))
        for text in paragraphs:
            if text.startswith("- "):
                story.append(Paragraph("• " + text[2:], BULLET))
            else:
                story.append(Paragraph(text, BODY))
    story.append(Spacer(1, 6))
    return story


def render(doc: dict, total_pages: int) -> int:
    """Write the PDF once and return how many pages it has."""

    def draw_header_and_footer(canvas, document):
        # Drawn on every page, like a real controlled document.
        canvas.saveState()
        canvas.setFont("Helvetica", 8.5)
        canvas.setFillGray(0.35)
        _, height = A4
        canvas.drawString(2.2 * cm, height - 1.3 * cm, HEADER)
        canvas.drawString(2.2 * cm, 1.2 * cm,
                          f"{doc['code']}  |  Version {doc['version']}  |  Effective {doc['effective']}"
                          f"  |  Page {document.page} of {total_pages}")
        canvas.restoreState()

    pdf = SimpleDocTemplate(str(OUT_DIR / doc["file"]), pagesize=A4,
                            leftMargin=2.2 * cm, rightMargin=2.2 * cm, topMargin=2.2 * cm, bottomMargin=2.2 * cm,
                            title=doc["title"], author="Helix Pharma Distribution (fictional)")
    pdf.build(make_story(doc), onFirstPage=draw_header_and_footer, onLaterPages=draw_header_and_footer)
    return pdf.page


def build_pdf(doc: dict) -> Path:
    # Render twice: the first pass only counts pages so the footer can say "Page X of Y".
    page_count = render(doc, total_pages=0)
    render(doc, total_pages=page_count)
    return OUT_DIR / doc["file"]


if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for document in DOCUMENTS:
        print("wrote", build_pdf(document).relative_to(OUT_DIR.parents[1]))
