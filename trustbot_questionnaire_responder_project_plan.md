# TrustBot / Questionnaire Responder Project Plan

## 1. Executive Summary

This document consolidates the prior planning around two closely related product concepts:

1. **TrustBot / Trust Center Launchpad**: a tool for early-stage and growth-stage companies that need to quickly create a professional security package, lightweight trust center, evidence library, and approved security response library.
2. **Questionnaire Responder**: a deeper internal knowledge base and RAG-powered workflow that drafts responses to security questionnaires using verified company evidence, control mappings, tenant-specific context, reviewer approval, and audit logs.

The combined product vision is a secure, evidence-grounded platform that helps companies organize their security posture, produce a customer-facing security package, and answer third-party security questionnaires without inventing unsupported claims.

The core principle is simple:

> The system should never guess about a company’s security posture. It should answer only from approved policies, controls, evidence, and reviewed organizational facts. When evidence is missing, stale, ambiguous, or outside scope, the system should flag the item for human review.

This project can be built in stages, starting as a practical internal tool or solo-developer MVP, then evolving into a SaaS-style product if desired.

---

## 2. Product Names and Related Concepts

### 2.1 TrustBot

**TrustBot** was the broad security automation concept. Earlier versions focused on third-party risk assessment automation, vendor intake, tiering, questionnaire generation, trust portal review, OSINT checks, threat modeling, and final risk report generation.

For this document, TrustBot is framed as the outward-facing and company-readiness product:

- Helps a company prepare a security package.
- Creates a trust center-style microsite or export.
- Builds a structured internal security knowledge base.
- Creates a reusable answer library for customer questionnaires.
- Organizes evidence and policies for due diligence.

### 2.2 Trust Center Launchpad

**Trust Center Launchpad** was an MVP framing for new companies that need to look organized during enterprise procurement.

The MVP included:

- Hosted trust center microsite.
- Security overview page.
- Standard security FAQ.
- Evidence inventory.
- Questionnaire responder.
- Master control catalog.
- Tenant or customer overlay.
- Evidence vault.
- Review and approval flow.

### 2.3 Security Ramp

**Security Ramp** was a service or sprint-style framing for a 10 to 14 day readiness process for B2B SaaS companies preparing for enterprise security reviews.

Potential deliverables included:

- Trust page.
- Source-of-truth matrix.
- Preapproved questionnaire answer library.
- One dry-run questionnaire.
- Enablement package.
- CSV schemas.
- Mermaid system-boundary diagram template.
- Canonical question domains.
- Answer templates.
- Status and tagging rules.

### 2.4 Questionnaire Responder

**Questionnaire Responder** was the more technical product concept. It is a multi-tenant AI system to draft and complete security questionnaires using:

- A global catalog of controls.
- Cross-framework mappings.
- Customer-specific evidence and policies.
- Hybrid retrieval.
- Structured answer generation.
- Evidence citations.
- Reviewer approval.
- Audit logs.
- Export formats such as SIG, CAIQ, CSV, spreadsheet, and possibly portal-compatible outputs.

---

## 3. Target Users

### 3.1 Primary Users

The first user groups are:

- Startups selling into enterprise customers.
- Small and mid-sized SaaS companies without mature GRC teams.
- Security leads who repeatedly answer customer due diligence questionnaires.
- Founders or operations leaders who need to present a credible security posture.
- GRC teams that need a controlled answer library and evidence vault.

### 3.2 Secondary Users

Secondary user groups include:

- Sales and customer success teams responding to procurement delays.
- Legal and compliance reviewers.
- Privacy teams.
- IT administrators.
- External auditors or consultants reviewing the company’s posture.

### 3.3 Internal Versus SaaS Use

Two deployment paths were discussed across related planning:

1. **Internal single-tenant version**
   - Built for one organization.
   - Highly secure.
   - No external customer tenanting at first.
   - Easier to control data access, workflows, and risk.

2. **Multi-tenant SaaS version**
   - Built for multiple companies.
   - Requires strict tenant isolation.
   - Requires stronger controls for authentication, authorization, encryption, audit logging, and data segregation.
   - More commercially scalable but more security-sensitive.

The safest build sequence is to start with a single-tenant or controlled beta version, then evolve toward multi-tenant once the core workflow is reliable.

---

## 4. Core Problem

Security questionnaires are slow, repetitive, and risky.

Companies often need to answer the same types of questions repeatedly:

- Do you encrypt data at rest?
- Do you encrypt data in transit?
- Do you have SOC 2?
- Do you perform access reviews?
- Do you have incident response procedures?
- Do you use MFA?
- Do you conduct vulnerability scans?
- Do you have a business continuity plan?
- Do you use subprocessors?
- Where is customer data hosted?
- What data do you collect?
- How do you manage third-party vendors?

The problem is not just speed. The larger problem is trustworthiness.

Poorly managed questionnaire responses can create risks such as:

- Inconsistent answers across customers.
- Unsupported claims.
- Outdated answers.
- Answers that do not reflect the actual environment.
- Sales teams overpromising security capabilities.
- Evidence being shared without proper review or redaction.
- Lack of audit trail for who approved an answer.
- Difficulty proving which source supported a response.

The proposed system solves this by treating questionnaire responses as controlled, evidence-backed outputs rather than ad hoc writing tasks.

---

## 5. Product Vision

The product should become the company’s security response operating system.

It should help a company:

1. Create a credible security package.
2. Build a verified internal security knowledge base.
3. Maintain an evidence vault.
4. Generate approved answers to questionnaires.
5. Track evidence freshness.
6. Route uncertain or high-risk answers to human reviewers.
7. Export completed questionnaires and customer-facing packages.
8. Maintain a durable audit trail.

Longer term, it could also support:

- Live trust centers.
- Customer-specific NDA-gated evidence rooms.
- Continuous monitoring of evidence freshness.
- Automated policy gap detection.
- Framework mapping.
- Questionnaire auto-import from spreadsheets, portals, PDFs, and documents.
- AI-assisted security package generation for early-stage companies.

---

## 6. Product Principles

### 6.1 Evidence First

Every answer should be grounded in a source:

- Policy.
- Procedure.
- Control record.
- System configuration evidence.
- Prior approved answer.
- Audit report.
- SOC 2 report.
- Penetration test summary.
- Vendor/subprocessor record.
- Architecture diagram.
- Data flow diagram.
- Risk assessment.
- BCP/DR test record.

### 6.2 Do Not Fabricate

The system must not create confident answers when the knowledge base does not support them.

Required fallback states:

- Unknown.
- Needs human input.
- Evidence missing.
- Evidence stale.
- Conflicting evidence.
- Out of scope.
- Requires legal/privacy review.
- Requires security owner review.

### 6.3 Human Review Before External Use

The system may draft answers, but external submission should require reviewer approval, especially for:

- Customer questionnaires.
- Contractual representations.
- Security commitments.
- Privacy-related claims.
- Data residency claims.
- Compliance certification claims.
- Incident response claims.
- Insurance or audit claims.

### 6.4 Version Everything

The system should keep versioned records of:

- Policies.
- Evidence.
- Control statements.
- Questionnaire answers.
- Approved answer templates.
- Exports.
- Reviewer decisions.
- Trust package versions.

### 6.5 Security by Design

The platform will contain sensitive security, compliance, architecture, and customer-response data. It must be designed as a high-security system from the beginning.

---

## 7. Core Modules

## 7.1 Company Profile Module

This module stores the organization’s basic security and operational facts.

Example fields:

- Company name.
- Product name.
- Company description.
- Hosting provider.
- Production regions.
- Primary infrastructure stack.
- Data types processed.
- Customer data categories.
- Authentication model.
- Encryption standards.
- Logging and monitoring tools.
- Incident response owner.
- Backup and disaster recovery summary.
- Subprocessors.
- Certifications and attestations.
- Security contact.
- Privacy contact.
- Data retention practices.

This module becomes the baseline source for the trust package and questionnaire responder.

---

## 7.2 Control Catalog Module

The control catalog is the structured security backbone of the system.

It should include canonical controls such as:

- Access control.
- Identity and authentication.
- Privileged access management.
- Encryption at rest.
- Encryption in transit.
- Vulnerability management.
- Secure SDLC.
- Change management.
- Logging and monitoring.
- Incident response.
- Business continuity.
- Disaster recovery.
- Vendor management.
- Data retention.
- Data deletion.
- Privacy and data protection.
- Security awareness training.
- Endpoint security.
- Network security.
- Cloud security.
- Asset management.
- Risk assessment.
- Compliance governance.

Each control should include:

- Control ID.
- Control title.
- Control domain.
- Control description.
- Implementation statement.
- Owner.
- Status.
- Applicable products or systems.
- Evidence references.
- Framework mappings.
- Last reviewed date.
- Next review date.
- Confidence level.
- Notes and exceptions.

---

## 7.3 Framework Mapping Module

The system should support mapping controls to common frameworks and questionnaire libraries.

Potential mappings:

- SOC 2 Trust Services Criteria.
- ISO 27001 / 27002.
- NIST Cybersecurity Framework.
- NIST 800-53.
- CIS Controls.
- CSA CAIQ / CCM.
- SIG Lite / SIG Core.
- GDPR-related data protection areas.
- HIPAA areas if relevant, but avoid health-regulated product positioning unless intended.
- PCI DSS if relevant.

The purpose is not to claim certification automatically. The purpose is to reuse control knowledge across questionnaires.

---

## 7.4 Evidence Vault

The evidence vault stores proof that supports company claims.

Evidence examples:

- SOC 2 report.
- ISO certificate.
- Penetration test executive summary.
- Vulnerability scan report.
- Access review export.
- Security awareness completion report.
- Incident response policy.
- BCP/DR test results.
- Backup configuration screenshots.
- Encryption configuration evidence.
- SSO/MFA configuration screenshots.
- Asset inventory export.
- Vendor inventory.
- Data flow diagram.
- Network diagram.
- Secure SDLC policy.
- Change management ticket samples.
- Risk register entries.

Evidence metadata should include:

- Evidence ID.
- Tenant ID or company ID.
- File name.
- File type.
- Evidence category.
- Associated controls.
- Source system.
- Owner.
- Confidentiality level.
- Customer-shareable status.
- NDA required flag.
- Redaction required flag.
- Expiration or review date.
- Upload date.
- Last reviewed date.
- Version.
- Hash/checksum.
- Storage path.
- Extracted text status.
- Approval status.

---

## 7.5 Knowledge Base Module

The internal knowledge base is used by the RAG workflow.

It should combine:

- Company profile facts.
- Control catalog records.
- Evidence text.
- Approved answer templates.
- Prior reviewed questionnaire answers.
- Framework mappings.
- Policy excerpts.
- System descriptions.
- Exceptions and limitations.

Important design decision:

> The knowledge base should separate verified source material from AI-generated summaries.

AI-generated summaries can help reviewers, but approved source records should remain distinct and traceable.

---

## 7.6 Questionnaire Intake Module

The system should ingest questionnaires from multiple formats.

MVP formats:

- CSV.
- Excel spreadsheet.
- Manual question entry.

Later formats:

- PDF.
- Word document.
- SIG workbook.
- CAIQ spreadsheet.
- Web portal copy/paste.
- Browser extension capture.
- API integration with procurement portals.

For each question, the system should capture:

- Original question text.
- Question ID from source file.
- Section/category.
- Answer type.
- Required field format.
- Customer name.
- Due date.
- Associated product or service.
- Required evidence, if any.
- Reviewer assignment.
- Status.

---

## 7.7 Questionnaire Classification Module

Each question should be classified before retrieval and generation.

Useful classification fields:

- Domain.
- Subdomain.
- Risk level.
- Question intent.
- Answer type.
- Product scope.
- Evidence required.
- Framework alignment.
- Owner team.
- Legal/privacy sensitivity.
- Whether the answer can be auto-drafted.
- Whether human approval is required.

Example domains:

- Access control.
- Encryption.
- Data storage.
- Data sharing.
- Incident response.
- Vulnerability management.
- Network security.
- Compliance certifications.
- Business continuity.
- Privacy.
- Third-party/vendor management.
- Secure development.
- Logging and monitoring.
- Physical security.
- HR security.
- Risk management.

---

## 7.8 Answer Generation Module

The answer generation module drafts responses using retrieved source material.

The system should generate structured answers, not just plain text.

Recommended answer JSON:

```json
{
  "question_id": "Q-001",
  "answer": "Yes. The company enforces MFA for administrative access and supports SSO for customer access where configured.",
  "short_answer": "Yes",
  "claim": "MFA is enforced for administrative access.",
  "scope": "Production administrative systems and company-managed access paths.",
  "evidence_refs": ["EV-1001", "CTRL-AC-004"],
  "source_quotes": [],
  "exceptions": "Customer SSO availability may depend on the customer plan or configuration.",
  "confidence": "high",
  "needs_human_review": true,
  "review_reason": "External customer response requires approval.",
  "freshness_status": "current",
  "last_reviewed": "2026-06-04"
}
```

The system should support multiple answer modes:

- Short yes/no.
- Long-form narrative.
- Customer-friendly response.
- Technical response.
- Internal reviewer note.
- Evidence request.
- Exception statement.
- Follow-up clarification.

---

## 7.9 Reviewer Workflow Module

The reviewer workflow should allow humans to approve, reject, edit, and comment on generated answers.

Statuses:

- Not started.
- Parsed.
- Classified.
- Draft generated.
- Needs evidence.
- Needs subject matter expert.
- Needs privacy review.
- Needs legal review.
- Approved.
- Rejected.
- Exported.
- Submitted.
- Archived.

Reviewer actions:

- Approve answer.
- Edit answer.
- Request evidence.
- Assign to owner.
- Mark as unsupported.
- Mark out of scope.
- Add exception.
- Attach evidence.
- Save as approved reusable answer.
- Export.

---

## 7.10 Trust Package Generator

The trust package generator creates a polished security package for new companies.

Potential sections:

1. Company security overview.
2. Product and architecture summary.
3. Data protection overview.
4. Access control overview.
5. Encryption overview.
6. Secure development practices.
7. Vulnerability management.
8. Logging and monitoring.
9. Incident response.
10. Business continuity and disaster recovery.
11. Vendor and subprocessor management.
12. Compliance and attestations.
13. Privacy and data handling.
14. Customer security FAQ.
15. Evidence index.
16. Security contact information.

Output formats:

- Markdown.
- PDF.
- Web trust center page.
- Customer-specific package.
- NDA-gated evidence room.

---

## 7.11 Trust Center Microsite

The trust center microsite is a customer-facing web page or portal.

Core pages:

- Overview.
- Security.
- Privacy.
- Compliance.
- Subprocessors.
- FAQs.
- Request access to documents.
- Contact security.

Possible gated documents:

- SOC 2 report.
- Penetration test summary.
- Security whitepaper.
- BCP/DR summary.
- Architecture diagram.
- Data flow diagram.
- Standard questionnaire export.

Access controls:

- Public pages.
- NDA-gated pages.
- Customer-specific links.
- Expiring document links.
- Download audit logs.

---

## 7.12 Export Module

The product should export completed outputs.

MVP exports:

- CSV.
- Excel.
- Markdown.
- PDF.

Later exports:

- SIG Lite.
- SIG Core.
- CAIQ.
- Customer-specific spreadsheet templates.
- Portal-ready answer blocks.
- API output.

Each export should retain:

- Export version.
- Questionnaire ID.
- Customer name.
- Approved answer state.
- Evidence references.
- Reviewer name.
- Export timestamp.
- Generated package hash or checksum.

---

## 8. System Architecture

## 8.1 Recommended MVP Architecture

A practical MVP architecture:

- **Frontend**: Next.js / React.
- **Backend**: Python FastAPI.
- **Database**: PostgreSQL.
- **Vector search**: pgvector inside PostgreSQL for MVP.
- **File storage**: Google Cloud Storage or AWS S3.
- **Queue/background jobs**: Cloud Tasks, Pub/Sub, Celery, or similar.
- **LLM provider**: OpenAI API for initial build, with abstraction layer to support other models later.
- **Embeddings**: embedding model used for document and question retrieval.
- **Auth**: Auth0, Clerk, Firebase Auth, or enterprise SSO later.
- **Hosting**: Google Cloud Run or similar container hosting.
- **Secrets**: Google Secret Manager or equivalent.
- **Observability**: structured logs, error tracking, audit logs.

For a solo developer with limited coding experience, a simpler first version can use:

- Next.js frontend.
- FastAPI backend.
- Supabase Postgres with pgvector.
- Supabase Storage or GCS.
- OpenAI API.
- Manual CSV/Excel upload.
- Basic reviewer dashboard.

---

## 8.2 Preferred Cloud Option

GCP was previously considered suitable for the user’s projects. A GCP implementation could use:

- Cloud Run for backend services.
- Cloud SQL for PostgreSQL.
- pgvector for vector retrieval.
- Google Cloud Storage for evidence files.
- Secret Manager for API keys and credentials.
- Cloud Tasks or Pub/Sub for document processing jobs.
- Cloud Logging for operational logs.
- Cloud KMS for encryption key management if needed.

---

## 8.3 Database and Storage Split

The system should separate structured metadata from raw files.

**PostgreSQL** stores:

- Tenants.
- Users.
- Roles.
- Controls.
- Framework mappings.
- Evidence metadata.
- Questionnaires.
- Questions.
- Answers.
- Reviews.
- Audit events.
- Export records.

**Object storage** stores:

- Uploaded evidence files.
- Extracted documents.
- Generated exports.
- Trust package PDFs.
- Customer-specific packages.

**Vector index** stores:

- Embedded control descriptions.
- Embedded evidence excerpts.
- Embedded approved answer templates.
- Embedded policy excerpts.
- Embedded prior reviewed answers.

---

## 9. Data Model

## 9.1 Core Tables

### tenants

For SaaS or multi-company use.

Fields:

- id.
- name.
- domain.
- plan.
- status.
- created_at.
- updated_at.

### users

Fields:

- id.
- tenant_id.
- name.
- email.
- role.
- status.
- last_login_at.
- created_at.

### roles

Example roles:

- Admin.
- Security Reviewer.
- Evidence Owner.
- Sales Viewer.
- Legal Reviewer.
- Privacy Reviewer.
- External Customer Viewer.

### company_profile

Fields:

- tenant_id.
- product_name.
- company_summary.
- hosting_provider.
- data_regions.
- data_types.
- security_contact.
- privacy_contact.
- compliance_status.
- last_reviewed_at.

### controls

Fields:

- id.
- tenant_id.
- control_code.
- domain.
- title.
- description.
- implementation_statement.
- owner.
- status.
- applicable_scope.
- review_frequency.
- last_reviewed_at.
- next_review_at.

### framework_mappings

Fields:

- id.
- control_id.
- framework.
- framework_control_id.
- mapping_strength.
- notes.

### evidence

Fields:

- id.
- tenant_id.
- title.
- file_name.
- file_type.
- storage_path.
- evidence_type.
- owner.
- confidentiality.
- customer_shareable.
- nda_required.
- redaction_required.
- status.
- version.
- hash.
- uploaded_at.
- last_reviewed_at.
- expires_at.

### evidence_control_links

Fields:

- id.
- evidence_id.
- control_id.
- relationship_type.
- notes.

### knowledge_chunks

Fields:

- id.
- tenant_id.
- source_type.
- source_id.
- chunk_text.
- embedding.
- chunk_metadata.
- created_at.

### questionnaires

Fields:

- id.
- tenant_id.
- customer_name.
- source_file.
- status.
- due_date.
- owner.
- created_at.
- updated_at.

### questions

Fields:

- id.
- questionnaire_id.
- original_question_id.
- question_text.
- section.
- answer_type.
- domain.
- classification_json.
- status.

### answers

Fields:

- id.
- question_id.
- answer_text.
- short_answer.
- claim.
- scope.
- exceptions.
- confidence.
- needs_human_review.
- review_reason.
- evidence_refs_json.
- model_used.
- prompt_version.
- created_at.
- updated_at.

### answer_reviews

Fields:

- id.
- answer_id.
- reviewer_id.
- decision.
- comments.
- reviewed_at.

### approved_answer_library

Fields:

- id.
- tenant_id.
- canonical_question.
- approved_answer.
- domain.
- controls.
- evidence_refs.
- scope.
- exceptions.
- approval_status.
- last_reviewed_at.

### audit_log

Fields:

- id.
- tenant_id.
- actor_user_id.
- action.
- object_type.
- object_id.
- old_value.
- new_value.
- ip_address.
- user_agent.
- timestamp.

### exports

Fields:

- id.
- tenant_id.
- questionnaire_id.
- export_type.
- storage_path.
- version.
- created_by.
- created_at.

---

## 10. RAG Design

## 10.1 Retrieval Sources

The RAG system should retrieve from:

- Company profile.
- Control catalog.
- Evidence text.
- Approved answer library.
- Prior approved questionnaire answers.
- Policy documents.
- Framework mappings.
- Exceptions register.

## 10.2 Hybrid Retrieval

Hybrid retrieval should combine:

1. **Keyword search** for exact terms such as SOC 2, MFA, AES-256, SSO, ISO 27001.
2. **Semantic vector search** for related concepts and differently worded questions.
3. **Metadata filtering** for tenant, product, scope, domain, evidence freshness, and customer-shareable status.

## 10.3 Retrieval Rules

The system should filter by:

- Tenant ID.
- Product or service scope.
- Approved records only.
- Current evidence when possible.
- Customer-shareable evidence where external response requires attachment.
- Domain classification.

The system should avoid retrieving:

- Draft policies unless explicitly allowed.
- Expired evidence unless marked usable with caution.
- Another tenant’s data.
- Unapproved AI-generated summaries.
- Internal-only details when creating customer-facing outputs.

## 10.4 Answer Grounding

Each answer should include:

- Main answer.
- Supporting evidence IDs.
- Source chunk references.
- Confidence score.
- Reason for review if needed.
- Exception text if the answer is not clean.

## 10.5 Unknown Fallback Logic

The model should return a structured unknown state when it cannot answer.

Example:

```json
{
  "answer": null,
  "short_answer": "Unknown",
  "confidence": "low",
  "needs_human_review": true,
  "review_reason": "No approved evidence was found to support this claim.",
  "evidence_refs": [],
  "recommended_next_step": "Request evidence from the security owner."
}
```

---

## 11. Agentic Workflow

The system does not need many autonomous agents at first. A small controlled workflow is safer.

## 11.1 Suggested Workflow Steps

1. Upload questionnaire.
2. Parse questions.
3. Classify questions.
4. Retrieve relevant controls and evidence.
5. Generate structured draft answer.
6. Score confidence.
7. Flag uncertain answers.
8. Route for human review.
9. Store approved answers.
10. Export completed questionnaire.
11. Log every action.

## 11.2 Possible Agents or Services

### Parser Agent

Extracts questions from spreadsheets, documents, or pasted content.

### Classifier Agent

Assigns domain, subdomain, answer type, sensitivity, and reviewer path.

### Retrieval Agent

Finds relevant controls, evidence, and prior answers.

### Answer Drafting Agent

Creates structured answer JSON.

### Evidence Gap Agent

Identifies missing, stale, or conflicting evidence.

### Reviewer Assistant

Summarizes why an answer was generated and what evidence supports it.

### Export Agent

Converts approved responses into requested formats.

The MVP can implement these as backend functions rather than fully autonomous agents.

---

## 12. User Interface Layout

## 12.1 Main Navigation

Recommended app navigation:

1. Dashboard.
2. Company Profile.
3. Controls.
4. Evidence Vault.
5. Questionnaires.
6. Answer Library.
7. Trust Package.
8. Trust Center.
9. Reviews.
10. Audit Log.
11. Settings.

---

## 12.2 Dashboard

Dashboard widgets:

- Open questionnaires.
- Questions needing review.
- Evidence expiring soon.
- Controls missing evidence.
- Recently approved answers.
- Exports created.
- Trust package status.
- Risk/gap summary.

---

## 12.3 Company Profile Screen

Sections:

- Company basics.
- Product/service details.
- Infrastructure.
- Data handling.
- Security contacts.
- Compliance posture.
- Subprocessors.
- Review status.

---

## 12.4 Control Catalog Screen

Layout:

- Left filter panel by domain/framework/status.
- Main control table.
- Control detail drawer.
- Evidence links.
- Mapping links.
- Review history.

---

## 12.5 Evidence Vault Screen

Layout:

- Upload evidence button.
- Evidence table.
- Filters by type, owner, control, status, expiration, customer-shareable.
- Evidence detail page.
- Extracted text preview.
- Linked controls.
- Redaction status.
- Download access log.

---

## 12.6 Questionnaire Workspace

This is the core working screen.

Recommended layout:

- Left panel: question list with status indicators.
- Center panel: selected question and draft answer.
- Right panel: supporting evidence, source chunks, prior answers, reviewer notes.
- Bottom panel or tab: audit history and comments.

Each question should show:

- Original question.
- Classified domain.
- Draft answer.
- Confidence.
- Evidence references.
- Exceptions.
- Review status.
- Owner.
- Action buttons: approve, edit, request evidence, assign, reject, save to library.

---

## 12.7 Answer Library Screen

Purpose:

- Manage reusable approved answers.
- Search by question topic.
- Review freshness.
- See evidence behind each answer.
- Track where answers were used.

Fields:

- Canonical question.
- Approved answer.
- Domain.
- Scope.
- Evidence.
- Owner.
- Last reviewed.
- Next review.
- Status.

---

## 12.8 Trust Package Builder

Wizard-style layout:

1. Select product/company profile.
2. Select security domains to include.
3. Select approved evidence references.
4. Generate draft package.
5. Review/edit sections.
6. Approve final package.
7. Export to PDF/Markdown or publish to trust center.

---

## 12.9 Trust Center Admin

Pages:

- Public overview.
- Security page.
- Compliance page.
- Privacy page.
- Subprocessors page.
- FAQ page.
- Document request settings.
- Access logs.

---

## 13. Security Architecture

## 13.1 Security Requirements

The product must be treated as a sensitive GRC/security data system.

Required controls:

- Strong authentication.
- Role-based access control.
- Tenant isolation if multi-tenant.
- Row-level security if shared database.
- Encryption at rest.
- Encryption in transit.
- Secrets management.
- Audit logging.
- Evidence access logging.
- Least privilege service accounts.
- Secure file upload handling.
- Malware scanning for uploaded files.
- Signed URLs for downloads.
- Expiring access links.
- Redaction support.
- Backups.
- Disaster recovery plan.
- Logging and monitoring.

## 13.2 Tenant Isolation

For multi-tenant SaaS:

- Every tenant-scoped table must include tenant_id.
- API authorization must enforce tenant_id.
- Database row-level security should enforce tenant boundaries.
- Object storage paths should be tenant-scoped.
- Vector retrieval must filter by tenant_id.
- Audit logs must include tenant_id.
- Background jobs must carry tenant context.

## 13.3 Evidence Protection

Evidence files may include sensitive details. Controls should include:

- Access control by role.
- Customer-shareable flag.
- NDA-required flag.
- Redaction-required flag.
- Document expiration.
- Download logging.
- Watermarking later.
- Document hash/checksum.
- Versioning.

## 13.4 Prompt Injection Defense

Uploaded documents and questionnaires may contain malicious instructions. The system must treat uploaded content as untrusted data.

Controls:

- Do not allow document text to override system instructions.
- Use strict prompts that distinguish source text from instructions.
- Strip or flag suspicious prompt-like content.
- Do not execute links or scripts from documents.
- Restrict model access to only approved retrieved context.
- Require structured output validation.

## 13.5 Model Output Controls

The system should validate model output before saving.

Validation checks:

- Required JSON fields present.
- Confidence is within allowed values.
- Evidence references exist.
- Evidence references belong to the tenant.
- Answer does not cite missing evidence.
- Answer does not claim certification unless certification exists.
- External answer does not include internal-only text.
- Unsupported answers are routed to review.

---

## 14. Trust Package Content Structure

## 14.1 Security Overview

Purpose:

- Provide a clear, customer-friendly summary of the company’s security posture.

Sections:

- Security governance.
- Infrastructure security.
- Data protection.
- Access control.
- Secure development.
- Monitoring and incident response.
- Business continuity.
- Vendor management.

## 14.2 Security FAQ

Standard FAQ questions:

- Do you encrypt data at rest?
- Do you encrypt data in transit?
- Do you support SSO?
- Is MFA required for employees?
- Do you perform background checks?
- Do you conduct security awareness training?
- Do you perform vulnerability scans?
- Do you conduct penetration testing?
- Do you have incident response procedures?
- Do you have backups?
- Do you have a disaster recovery plan?
- Do you use subprocessors?
- Where is data hosted?
- How do you delete customer data?
- Do you have SOC 2 or ISO certification?

## 14.3 Evidence Index

Evidence index should show:

- Evidence title.
- Description.
- Shareability status.
- Review date.
- Expiration date.
- Controls supported.
- Whether NDA is required.

## 14.4 Subprocessor List

Fields:

- Vendor name.
- Service purpose.
- Data accessed.
- Location/region.
- Security review status.
- DPA status.
- Link to vendor trust page.
- Last reviewed.

---

## 15. Build Roadmap

## 15.1 Phase 0: Product Definition

Goal: lock the MVP scope.

Tasks:

- Define target user: startup security package, internal questionnaire responder, or both.
- Choose single-tenant first or multi-tenant from day one.
- Define core questionnaire formats.
- Define minimum evidence types.
- Define approval workflow.
- Define exports.
- Define data retention rules.

Recommended decision:

> Build a single-tenant MVP first that can later become multi-tenant. This keeps the first build smaller and safer.

---

## 15.2 Phase 1: Source-of-Truth Foundation

Goal: create the structured knowledge base.

Build:

- Company profile module.
- Control catalog module.
- Evidence vault metadata.
- Manual evidence upload.
- Basic policy/evidence text extraction.
- Simple control-to-evidence linking.
- Basic audit log.

Outputs:

- Company security profile.
- Control catalog.
- Evidence inventory.
- First source-of-truth matrix.

---

## 15.3 Phase 2: Questionnaire MVP

Goal: answer questionnaires from controlled internal knowledge.

Build:

- CSV/Excel questionnaire upload.
- Question parser.
- Question classification.
- Retrieval over controls/evidence/approved answers.
- Structured answer generation.
- Reviewer dashboard.
- Export to CSV/Excel.

Outputs:

- Completed questionnaire draft.
- Evidence-backed answers.
- Review workflow.
- Approved answer library.

---

## 15.4 Phase 3: Trust Package Generator

Goal: turn internal security facts into a professional external package.

Build:

- Security package wizard.
- Markdown/PDF generation.
- Security FAQ builder.
- Evidence index.
- Review and approval.

Outputs:

- Security overview document.
- Security FAQ.
- Evidence index.
- Customer-ready trust package.

---

## 15.5 Phase 4: Trust Center Microsite

Goal: publish approved security information.

Build:

- Public trust center pages.
- Admin publishing flow.
- NDA-gated document access.
- Access request workflow.
- Download logs.

Outputs:

- Hosted trust center microsite.
- Controlled evidence sharing.
- Customer-facing document portal.

---

## 15.6 Phase 5: Advanced Automation

Goal: improve scale and quality.

Potential features:

- SIG/CAIQ export.
- PDF/Word parsing.
- Browser extension for portal questionnaires.
- AI evidence gap detection.
- Evidence freshness alerts.
- Framework mapping automation.
- Customer-specific answer tone.
- Redaction assistant.
- Watermarked downloads.
- SSO and SCIM.
- Trust score or readiness score.
- API integrations.

---

## 16. MVP Scope Recommendation

The MVP should avoid trying to build everything at once.

Recommended MVP:

1. Login/auth.
2. Company profile.
3. Control catalog.
4. Evidence vault.
5. CSV/Excel questionnaire upload.
6. Question classification.
7. Retrieval from company profile, controls, evidence, and approved answer library.
8. Structured AI answer draft.
9. Human review workflow.
10. Export to Excel/CSV.
11. Basic trust package Markdown/PDF.
12. Audit log.

Do not include in MVP:

- Full browser extension.
- Automatic portal submission.
- Complex OSINT.
- Autonomous customer communication.
- Continuous monitoring.
- Heavy framework certification claims.
- Fully automated approval.
- Complex multi-tenant billing.

---

## 17. Suggested First Screens to Build

A practical first implementation order:

1. **Company Profile**
   - This gives the system basic facts.

2. **Control Catalog**
   - This gives the system structured security claims.

3. **Evidence Vault**
   - This gives the system support for claims.

4. **Questionnaire Upload**
   - This creates the first high-value workflow.

5. **Questionnaire Workspace**
   - This is where users review and approve answers.

6. **Answer Library**
   - This makes the system improve over time.

7. **Trust Package Builder**
   - This creates the external deliverable.

---

## 18. AI Prompting Strategy

## 18.1 System Instruction Pattern

The answer-generation prompt should enforce:

- Use only retrieved evidence.
- Do not invent policies.
- Do not claim certifications unless directly supported.
- Preserve scope and exceptions.
- Prefer concise customer-safe language.
- Return structured JSON.
- Flag missing evidence.
- Flag stale evidence.
- Require human review for external use.

## 18.2 Draft Answer Prompt Inputs

Inputs:

- Question text.
- Customer context.
- Product scope.
- Retrieved controls.
- Retrieved evidence excerpts.
- Approved answer examples.
- Known exceptions.
- Required output schema.

## 18.3 Answer Evaluation Prompt

A second model call or deterministic rule set can evaluate:

- Does the answer match the evidence?
- Does the answer overclaim?
- Are certifications named correctly?
- Is the scope clear?
- Is there an exception?
- Is human review required?

For the MVP, deterministic validation rules should be used wherever possible.

---

## 19. Security Questionnaire Answer Quality Rules

Good answers should be:

- Accurate.
- Evidence-backed.
- Scoped.
- Consistent.
- Customer-safe.
- Not overly verbose.
- Not misleading.
- Not overcommitted.
- Clear about exceptions.
- Reviewed before external use.

Bad answers include:

- Unsupported claims.
- “Yes” answers without evidence.
- Vague claims like “industry standard” without detail.
- Promises about future controls as if they exist today.
- Claims that apply to one product but not another.
- Internal details that should not be shared externally.
- Answers copied from one customer context into another without scope review.

---

## 20. Example Workflow

### Scenario

A customer sends a 200-question security questionnaire.

### Workflow

1. User uploads the questionnaire.
2. System parses each row into a question record.
3. System classifies questions by domain.
4. System retrieves relevant controls and evidence.
5. System drafts answer JSON.
6. System flags low-confidence answers.
7. Reviewer approves, edits, or assigns questions.
8. Approved answers are saved to the answer library.
9. System exports the completed questionnaire.
10. Audit log records all changes and approvals.

### Output

The customer receives a complete, consistent, reviewed questionnaire with answers that can be traced back to approved evidence.

---

## 21. Example Trust Package Workflow

### Scenario

A new SaaS company needs a customer-ready security package.

### Workflow

1. User enters company profile.
2. User uploads existing policies and evidence.
3. System maps documents to control domains.
4. System identifies missing evidence and weak sections.
5. User fills gaps manually.
6. System drafts security overview.
7. System drafts FAQ.
8. Reviewer approves content.
9. System exports Markdown/PDF.
10. Optional: publish approved sections to trust center.

### Output

The company receives a polished security package that can be reused in sales, procurement, and customer security reviews.

---

## 22. Key Differentiators

Potential differentiators:

1. Evidence-backed answers, not generic AI text.
2. Built specifically for security questionnaire workflows.
3. Combines trust package generation and questionnaire response.
4. Designed for early-stage companies without mature GRC teams.
5. Human approval and audit logs built in from the start.
6. Explicit unknown fallback when evidence is missing.
7. Control catalog and answer library improve over time.
8. Customer-facing trust center can be generated from the same internal knowledge base.
9. Framework mappings allow answers to be reused across many questionnaire types.
10. Security-sensitive architecture rather than a generic chatbot wrapper.

---

## 23. Risks and Mitigations

## 23.1 Hallucinated Answers

Risk: AI creates unsupported answers.

Mitigation:

- Strict RAG.
- Evidence references required.
- Unknown fallback.
- Reviewer approval.
- Output validation.

## 23.2 Data Leakage

Risk: one customer or tenant sees another tenant’s security data.

Mitigation:

- Tenant-scoped retrieval.
- Row-level security.
- Object storage isolation.
- Authorization checks.
- Audit logs.

## 23.3 Over-Sharing Sensitive Evidence

Risk: confidential internal evidence is exposed externally.

Mitigation:

- Customer-shareable flag.
- NDA-required flag.
- Redaction workflow.
- Access logs.
- Expiring links.

## 23.4 Stale Evidence

Risk: old evidence supports current claims incorrectly.

Mitigation:

- Evidence expiration dates.
- Freshness status.
- Review reminders.
- Stale evidence warning.

## 23.5 Overcomplicated MVP

Risk: trying to build trust center, questionnaire automation, OSINT, portal automation, and continuous monitoring at once.

Mitigation:

- Start with source of truth, evidence vault, questionnaire upload, reviewer workflow, and export.

---

## 24. Future Enhancements

Potential enhancements discussed or implied:

- Continuous monitoring.
- Vendor risk scorecards over time.
- Automated policy compliance checks.
- AI anomaly detection in answers.
- Reviewer assistant mode.
- Shared secrets vault.
- Vendor identity validation.
- Chain-of-trust mapping.
- Multi-team review.
- SLA escalation.
- Risk forecasting.
- Visual risk map.
- Self-audit mode.
- Executive summaries.
- Evidence retention policy.
- Versioned assessment history.
- Trust portal discovery.
- OSINT breach search.
- Threat modeling with Mermaid diagrams.
- Final security assessment report compilation.
- Browser-based questionnaire capture.
- Live questionnaire API.

Some of these belong more to the original internal third-party risk TrustBot system than the startup security package product. They should be considered later-stage modules, not MVP requirements.

---

## 25. Relationship to Original TrustBot Third-Party Risk System

The original TrustBot idea also included an internal third-party security review platform for reviewing vendors.

Original TrustBot capabilities included:

- Internal intake form.
- Vendor classification.
- High/Medium/Low tiering.
- Tiered questionnaire generation.
- Vendor portal for completion.
- Trust portal discovery.
- Document retrieval.
- RAG for questionnaire prefill.
- OSINT search.
- Breach search.
- LLM-based threat modeling.
- Mermaid diagram generation.
- Final assessment report synthesis.
- Human sign-off.

That workflow is adjacent but reversed.

- **Original TrustBot**: helps a buyer assess vendors.
- **Questionnaire Responder / Trust Center Launchpad**: helps a company respond to buyers.

The two systems could share technology:

- Questionnaire parsing.
- Evidence vault.
- RAG retrieval.
- Control catalog.
- Risk classification.
- Review workflow.
- Audit logging.
- Report generation.

However, they should not be combined too early. The questionnaire responder and trust package generator are more focused and easier to commercialize as a clear MVP.

---

## 26. Recommended Technical Stack

## 26.1 Solo Developer Friendly Stack

Frontend:

- Next.js.
- React.
- Tailwind CSS.

Backend:

- Python.
- FastAPI.

Database:

- PostgreSQL.
- pgvector.

Storage:

- Google Cloud Storage, AWS S3, or Supabase Storage.

AI:

- OpenAI API initially.
- Abstraction layer for future model changes.

Authentication:

- Clerk, Auth0, Firebase Auth, or Supabase Auth.

Hosting:

- Cloud Run, Render, Railway, Fly.io, or Vercel plus backend hosting.

Background jobs:

- Cloud Tasks, Celery, RQ, or simple worker process for MVP.

---

## 26.2 More Enterprise-Ready GCP Stack

- Cloud Run for FastAPI services.
- Cloud SQL Postgres with pgvector.
- Google Cloud Storage for evidence files.
- Secret Manager.
- Cloud KMS.
- Pub/Sub.
- Cloud Tasks.
- Cloud Logging.
- Cloud Monitoring.
- Identity Platform or external IdP.
- VPC/service perimeter later if required.

---

## 27. Build Sequence for a Solo Developer

### Step 1: Create the Database Schema

Start with:

- tenants or single company table.
- users.
- controls.
- evidence.
- questionnaires.
- questions.
- answers.
- answer_reviews.
- audit_log.

### Step 2: Build Basic Backend APIs

APIs:

- Create/update company profile.
- CRUD controls.
- Upload evidence metadata.
- Upload questionnaire.
- List questions.
- Generate draft answer.
- Approve/edit answer.
- Export questionnaire.

### Step 3: Build Basic Frontend

Screens:

- Dashboard.
- Company Profile.
- Controls.
- Evidence Vault.
- Questionnaire Workspace.

### Step 4: Add Embeddings and Retrieval

- Extract text from evidence.
- Chunk text.
- Create embeddings.
- Store chunks with metadata.
- Retrieve chunks by question.
- Filter by tenant and domain.

### Step 5: Add Answer Generation

- Send retrieved context to LLM.
- Require structured JSON.
- Validate output.
- Save answer draft.
- Flag review status.

### Step 6: Add Review Workflow

- Approve.
- Edit.
- Reject.
- Assign.
- Request evidence.
- Save to answer library.

### Step 7: Add Export

- Export questionnaire to CSV/Excel.
- Export security package to Markdown/PDF.

---

## 28. MVP Success Criteria

The MVP is successful if it can:

1. Store company security facts.
2. Store controls and evidence.
3. Upload a questionnaire.
4. Draft answers from retrieved evidence.
5. Refuse or flag unsupported questions.
6. Allow human approval.
7. Export reviewed answers.
8. Save approved answers for reuse.
9. Produce a basic security package.
10. Keep an audit trail.

---

## 29. Non-Goals for First Build

Avoid these in the first build:

- Automatic portal submission.
- Fully autonomous customer communication.
- Real-time continuous monitoring.
- Complex compliance certification automation.
- Unreviewed AI answers sent externally.
- Large marketplace of templates.
- Heavy multi-tenant billing logic.
- Native mobile app.
- Overbuilt workflow automation.

---

## 30. Open Decisions

The following decisions should be finalized before implementation:

1. Will the first version be internal single-tenant or SaaS multi-tenant?
2. Will the first paid offer be Trust Center Launchpad, Questionnaire Responder, or Security Ramp-style package?
3. Which questionnaire format will be supported first: CSV, Excel, SIG, or CAIQ?
4. Which frameworks matter for MVP?
5. What evidence types are required for the first version?
6. Should the trust center be public, gated, or export-only at first?
7. What approval roles are required?
8. What is the minimum acceptable audit log?
9. Which LLM provider and embedding model will be used initially?
10. Will customers upload real evidence in MVP, or will the first version use a guided manual knowledge-base form?

---

## 31. Recommended MVP Positioning

The strongest initial positioning is:

> An evidence-backed AI security questionnaire and trust package builder for B2B SaaS companies that need to pass customer security reviews faster without making unsupported claims.

A more concise version:

> Build your trust package. Answer security questionnaires. Prove every claim.

This positioning combines speed, trust, and defensibility.

---

## 32. Suggested Product Packages

### Package 1: Trust Package Starter

For companies with little documentation.

Includes:

- Company profile builder.
- Security overview generator.
- FAQ generator.
- Evidence checklist.
- Basic trust package export.

### Package 2: Questionnaire Responder

For companies receiving customer questionnaires.

Includes:

- Questionnaire upload.
- Answer drafting.
- Evidence-backed citations.
- Review workflow.
- Export.
- Approved answer library.

### Package 3: Trust Center Launchpad

For companies ready to publish a trust page.

Includes:

- Trust microsite.
- Public security overview.
- FAQ.
- Subprocessor list.
- Gated document access.
- Access logging.

---

## 33. Final Recommended Path

The best path is to build the system in this order:

1. **Source-of-truth builder**
   - Company profile, controls, evidence.

2. **Questionnaire responder**
   - Upload, classify, retrieve, draft, review, export.

3. **Approved answer library**
   - Reuse high-quality reviewed responses.

4. **Trust package generator**
   - Turn the same approved knowledge base into customer-facing collateral.

5. **Trust center microsite**
   - Publish the approved package and evidence access flow.

This path avoids building a generic chatbot. It creates a defensible security workflow where the data model, evidence vault, reviewer process, and audit trail are the actual product moat.

---

## 34. One-Page Build Blueprint

### Product

Evidence-backed AI questionnaire responder and trust package generator.

### Primary User

B2B SaaS company that needs to pass customer security reviews.

### Core Data

Company profile, controls, evidence, approved answers, questionnaire questions, answer reviews, audit logs.

### Core Workflow

Upload questionnaire → classify question → retrieve evidence → draft structured answer → human review → export → save approved answer.

### MVP Stack

Next.js + FastAPI + PostgreSQL/pgvector + object storage + OpenAI API + simple auth.

### First Deliverables

- Control catalog.
- Evidence vault.
- Questionnaire upload.
- Draft answer generator.
- Reviewer workspace.
- Export.
- Basic trust package.

### Must-Have Controls

- No unsupported answers.
- Evidence citations.
- Human review.
- Tenant isolation if SaaS.
- Audit logs.
- Evidence access controls.
- Versioning.

### Long-Term Moat

The moat is not just AI. The moat is the structured security source of truth, evidence freshness, approved answer library, review workflow, framework mappings, and trust package generation from verified internal knowledge.

