import os
import anthropic
import requests
import json
import time
import logging
import csv
from datetime import datetime, timedelta, timezone

# Read Contact and Company data from Apollo export CSV
def get_unprocessed_companies(filename='apollo-contacts-export.csv', limit=50):
    """Read unprocessed contacts from CSV"""
    processed = set()
    try:
        with open('processed.txt', 'r', encoding='utf-8') as f:
            processed = set(line.strip() for line in f)
    except FileNotFoundError:
        pass

    companies = []

    with open(filename, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    for i, row in enumerate(all_rows):
        company_name = row.get('Company Name', '')

        if company_name in processed:
            continue
        if row.get('Proceed', '').strip().lower() in ('done', 'exists'):
            continue

        company = {
            'first_name': row.get('First Name', ''),
            'last_name': row.get('Last Name', ''),
            'title': row.get('Title', ''),
            'email': row.get('Email', ''),
            'linkedin': row.get('Person Linkedin Url', ''),
            'name': company_name,
            'website': row.get('Website', ''),
            'industry': row.get('Industry', ''),
            'city': row.get('City', ''),
            'state': row.get('State', ''),
            'employees': row.get('# Employees', ''),
            'revenue': row.get('Annual Revenue', ''),
            'technologies': row.get('Technologies', ''),
            'linkedin_company': row.get('Company Linkedin Url', ''),
            'phone': row.get('Work Direct Phone', ''),
            'company_state': row.get('Company State', ''),
            'company_country': row.get('Company Country', ''),
            'row_index': i
        }

        companies.append(company)

        if len(companies) >= limit:
            break

    return companies, all_rows

def mark_company_processed(filename, all_rows, row_index, status='done'):
    """Mark company as done/exists in both processed.txt and CSV"""
    company_name = all_rows[row_index].get('Company Name', '')

    # Update processed.txt
    with open('processed.txt', 'a', encoding='utf-8') as f:
        f.write(company_name + '\n')

    # Update CSV Proceed column
    all_rows[row_index]['Proceed'] = status

    if all_rows:
        with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=all_rows[0].keys())
            writer.writeheader()
            writer.writerows(all_rows)

    log.info(f"Marked {company_name} as {status}")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('sdr_agent.log', encoding='utf-8'),
        logging.StreamHandler(stream=__import__('sys').stdout)
    ]
)

log = logging.getLogger(__name__)

import os

# API Keys — loaded from environment variables
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MANUS_API_KEY = os.environ.get("MANUS_API_KEY")
HUBSPOT_API_KEY = os.environ.get("HUBSPOT_API_KEY")

# HubSpot Rep IDs
EVELYN = "91727520"
ERICA = "57064994"

# US state -> rep, based on company location (Company State / Company Country)
# Any US state not listed here defaults to Erica. All Canada goes to Evelyn.
STATE_REP_MAP = {
    "Massachusetts": EVELYN,
    "Maine": ERICA,
    "New Jersey": EVELYN,
    "New York": EVELYN,
    "District of Columbia": ERICA,
    "Vermont": EVELYN,
    "Alaska": ERICA,
    "Connecticut": EVELYN,
    "Oklahoma": ERICA,
    "South Dakota": ERICA,
    "Maryland": EVELYN,
    "Michigan": EVELYN,
    "Ohio": EVELYN,
    "Illinois": EVELYN,
    "Missouri": EVELYN,
    "Minnesota": ERICA,
    "California": ERICA,
    "Nevada": ERICA,
    "Oregon": ERICA,
    "Hawaii": ERICA,
    "New Mexico": ERICA,
    "Arizona": ERICA,
    "Colorado": ERICA,
    "Washington": ERICA,
    "Montana": ERICA,
    "Virginia": EVELYN,
    "West Virginia": EVELYN,
    "Florida": EVELYN,
    "Mississippi": ERICA,
    "Pennsylvania": EVELYN,
}

def get_rep_for_company(company):
    """Assign a sales rep based on the company's state/province and country.
    All Canada -> Evelyn. US -> per STATE_REP_MAP, defaulting to Erica if the
    state isn't listed. Any other country also defaults to Erica."""
    country = (company.get('company_country') or '').strip().lower()
    state = (company.get('company_state') or '').strip()

    if country == 'canada':
        return EVELYN

    if country == 'united states':
        return STATE_REP_MAP.get(state, ERICA)

    # Unrecognized/other country — fall back to Erica
    return ERICA

def create_manus_task(company):
    """Send company to Manus for deep research"""
    log.info(f"Creating Manus task for {company['name']}")

    prompt = f"""You are a B2B sales researcher for Birchmount Network, a gift card solutions company specializing in regulated and specialty retail industries including cannabis, wineries, nightclubs, tobacco stores and similar businesses.

We already have this contact from Apollo:
Contact: {company['first_name']} {company['last_name']}, {company['title']}
Email: {company['email']}
LinkedIn: {company['linkedin']}

Company details:
Company: {company['name']}
Website: {company['website']}
Industry: {company['industry']}
City: {company['city']}
Employees: {company['employees']}
Revenue: {company['revenue']}
Technologies: {company['technologies']}

Your research tasks:

1. Visit their website and verify:
- Do they sell gift cards? Digital or physical? Easy to buy?
- Direct URL to gift card page if it exists
- Is there a loyalty or rewards program?
- Is there a corporate gifting program?
- Gift card balance checker?
- Quality of gift card experience: Modern or Outdated?

2. Find ONE additional key decision maker (different from {company['first_name']} {company['last_name']}) most likely to buy a gift card solution:
- Full name
- Title
- LinkedIn URL
- Direct email if publicly available (check their LinkedIn, company website team page, press releases)
- Direct phone if publicly available (check company website, LinkedIn, ZoomInfo snippets, Clutch profiles, Google Business)
- Why they are the right contact for Birchmount

For phone numbers specifically — check:
- Company website contact/team page
- Google Business listing
- LinkedIn profile
- Any press releases or news articles mentioning them

3. Technology & Loyalty verification:
Identify or confirm their E-commerce platform (e.g., Shopify, Magento, Salesforce)
Identify their POS system or Loyalty platform if visible on their website, job postings, LinkedIn profiles of employees, or any other public source. Check for any recent technology investments or changes mentioned in news or press releases.

4. Growth and intent signals:
- Recent news or expansion (last 6 months)
- New locations or hiring
- Any recent technology investments
- Social media activity level

5. Pain points OR Core Vulnerabilities (Look for at least one):
- Specific weaknesses in gift card program
- Customer retention gaps
- Missed B2B Revenue: No corporate/bulk gifting option.
- Low Engagement: No obvious way for users to register cards or opt-in to balance notifications.
- Broken UX: Clunky, outdated checkout experience or physical-only cards.

Only report verified facts. Flag anything as Unable to verify.
Return all findings as plain text. Do not create files or attachments."""

    response = requests.post(
        "https://api.manus.ai/v2/task.create",
        headers={
            "x-manus-api-key": MANUS_API_KEY,
            "Content-Type": "application/json"
        },
        json={
            "message": {
                "content": [{"type": "text", "text": prompt}]
            },
            "hide_in_task_list": True,
            "agent_profile": "manus-1.6-lite"
        }
    )

    data = response.json()
    if not data.get('ok'):
        error_code = data.get('error', {}).get('code', '')
        if error_code in ['payment_required', 'insufficient_credits', 'quota_exceeded']:
            raise Exception(f"MANUS_OUT_OF_CREDITS: {data}")
        raise Exception(f"Manus task creation failed: {data}")

    return data['task_id']

def poll_manus_until_complete(task_id, timeout=900):
    """Poll Manus until research is complete"""
    log.info(f"Polling Manus task {task_id}")
    start_time = time.time()
    attempt = 0

    while time.time() - start_time < timeout:
        attempt += 1
        response = requests.get(
            "https://api.manus.ai/v2/task.listMessages",
            headers={"x-manus-api-key": MANUS_API_KEY},
            params={"task_id": task_id}
        )

        data = response.json()
        messages = data.get('messages', [])

        for message in messages:
            # Check correct Manus message structure
            if message.get('type') == 'assistant_message':
                content = message.get('assistant_message', {}).get('content', '')
                if isinstance(content, str) and len(content) > 500:
                    log.info(f"Manus research complete - {len(content)} characters")
                    return content

            # Check for error status
            if message.get('type') == 'status_update':
                status = message.get('status_update', {}).get('agent_status', '')
                if status == 'error':
                    raise Exception(f"Manus task failed: {message}")

        log.info(f"Still waiting... attempt {attempt}, sleeping 30s")
        time.sleep(30)

    raise Exception(f"Manus timed out after {timeout}s")

def claude_qualify(company, manus_research):
    """Use Claude Opus to qualify and score the lead"""
    log.info(f"Running Claude qualification for {company['name']}")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""You are an expert SDR analyst for Birchmount Network, a gift card solutions company specializing in cannabis, wineries, nightclubs, tobacco and specialty retail, Our platform provides enterprise-grade gift card processing, a centralized cloud promotion engine (SMS/Email balance notifications), B2B/B2C distribution networks, and seamless e-commerce hosting that protects merchants from chargeback liability.

    ## VALUE PROPOSITIONS TO REFERENCE:
Expanding into modern e-commerce channels drives up to a 36% increase in gift card sales.
35% of cardholders want frequent balance reminders, which our automated notification engine provides via SMS/Email to drive faster redemption.
52% of businesses use gift cards for corporate rewards; Birchmount allows merchants to easily launch a B2B corporate distribution program.
Pushing gift cards into digital wallets (Apple/Google) generates up to 31% more spend.


## EXISTING APOLLO CONTACT
Name: {company['first_name']} {company['last_name']}
Title: {company['title']}
Email: {company['email']}
Phone: {company['phone']}
LinkedIn: {company['linkedin']}

## MANUS RESEARCH REPORT
{manus_research}

## APOLLO COMPANY DATA
Company: {company['name']}
Website: {company['website']}
Industry: {company['industry']}
City: {company['city']}
Employees: {company['employees']}
Revenue: {company['revenue']}

## YOUR TASK
## YOUR TASK
Qualify this prospect and generate highly personalized outreach hooks using the verified data from Manus.

CRITICAL RULES:
- Only state facts confirmed by Manus research
- Mark anything unverified as Unable to verify
- Never invent statistics or percentages
- For decision_makers: always include the Apollo contact as contact 1
- For contact 2: only include if Manus found a verified second contact
- Email fields: return only valid email format or empty string

Return ONLY this JSON — no markdown, no backticks, start with {{ end with }}:
{{
  "fit_score": "Platinum/Gold/Silver/Bronze",
  "priority": "High/Medium/Low",
  "intent_score": 1 to 10 based on growth signals and tech investments,
  "intent_signals": "specific dated signals or Unable to verify",
  "compliance_notes": "any regulatory considerations for gift cards in their state/province",
  "company_profile": {{
    "years_in_business": "value or Unable to verify",
    "locations": "value or Unable to verify",
    "revenue_range": "value or Unable to verify"
  }},
  "technology": {{
    "pos_system": "value or Unable to verify",
    "ecommerce_platform": "value or Unable to verify",
    "loyalty_platform": "value or Unable to verify"
  }},
  "gift_card_analysis": {{
    "has_gift_cards": true,
    "gift_card_url": "URL or Unable to verify",
    "experience_quality": "Modern/Outdated/None/Unable to verify",
    "corporate_gifting": false,
    "balance_checker": false
  }},
  "decision_makers": [
    {{
      "name": "{company['first_name']} {company['last_name']}",
      "title": "{company['title']}",
      "linkedin": "{company['linkedin']}",
      "email": "{company['email']}",
      "phone": "{company['phone']}",
      "why_right_contact": "1 sentence based on their title and role"
    }}
  ],
  "second_contact": {{
    "found": false,
    "name": "",
    "title": "",
    "linkedin": "",
    "email": "",
    "phone": "",
    "why_right_contact": ""
  }},
  "pain_points": "3 specific verified pain points",
  "account_summary": "2 paragraphs verified facts only",
  "opportunity_assessment": "2 paragraphs Birchmount opportunity",
  "outreach_angles": "Angle 1 | Angle 2 | Angle 3",
  "discovery_questions": "Q1 | Q2 | Q3 | Q4 | Q5",
  "executive_summary": "Why this score and whether to pursue",
  "draft_email_subject": "specific subject line",
  "draft_email_body": "under 120 words, verified facts only, personalized to contact name and company",
  "confidence_level": "High/Medium/Low",
  "research_notes": "things sales rep should verify"
}}"""

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text
    clean = raw.replace("```json", "").replace("```", "").strip()

    import re
    json_match = re.search(r'\{.*\}', clean, re.DOTALL)
    if json_match:
        clean = json_match.group(0)

    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        log.error(f"JSON parse error: {e}")
        log.error(f"Raw response: {clean[:500]}")
        raise Exception(f"Claude returned invalid JSON: {e}")


def create_hubspot_contact(contact, assessment, company, rep_id):
    """Create a contact in HubSpot or return existing contact ID"""
    name_parts = contact.get('name', '').split(' ', 1)
    first_name = name_parts[0] if name_parts else ''
    last_name = name_parts[1] if len(name_parts) > 1 else ''

    if not contact.get('name'):
        log.info(f"Skipping — no contact name found")
        return None

    payload = {
        "properties": {
            "firstname": first_name,
            "lastname": last_name,
            "email": contact.get('email', ''),
            "phone": contact.get('phone', ''),
            "jobtitle": contact.get('title', ''),
            "company": company.get('name'),
            "website": company.get('website'),
            "contact_source": "AI Agent",
            "hubspot_owner_id": rep_id,
            "fit_score": assessment.get('fit_score', ''),
            "current_pos_system": assessment.get('technology', {}).get('pos_system', ''),
            "gift_card_provider": assessment.get('gift_card_analysis', {}).get('experience_quality', '')
        }
    }

    response = requests.post(
        "https://api.hubapi.com/crm/v3/objects/contacts",
        headers={
            "Authorization": f"Bearer {HUBSPOT_API_KEY}",
            "Content-Type": "application/json"
        },
        json=payload
    )

    if response.status_code in [200, 201]:
        contact_id = response.json()['id']
        log.info(f"HubSpot contact created: {contact.get('name')} (ID: {contact_id})")
        return contact_id

    elif response.status_code == 409:
        # Contact already exists — extract existing ID and still create task
        error_data = response.json()
        message = error_data.get('message', '')

        # Extract existing contact ID from error message
        import re
        id_match = re.search(r'Existing ID: (\d+)', message)
        if id_match:
            existing_id = id_match.group(1)
            log.info(f"Contact already exists: {contact.get('name')} (ID: {existing_id}) — will still create task")
            return existing_id
        else:
            log.error(f"Contact exists but couldn't extract ID: {message}")
            return None

    else:
        log.error(f"HubSpot contact creation failed: {response.text}")
        return None

def create_hubspot_task(contact_id, contact, assessment, company, rep_id):
    """Create a follow-up task in HubSpot"""

    notes = f"""Score: {assessment.get('fit_score', '')}
Confidence Level: {assessment.get('confidence_level', '')}

COMPLIANCE NOTES:
{assessment.get('compliance_notes', '')}

Summary:
{assessment.get('account_summary', '')}

Opportunity Assessment:
{assessment.get('opportunity_assessment', '')}

Growth Signals:
{assessment.get('growth_signals', '')}

Pain Points:
{assessment.get('pain_points', '')}

Executive Summary:
{assessment.get('executive_summary', '')}

Outreach Angles:
{assessment.get('outreach_angles', '')}

Draft Email Subject: {assessment.get('draft_email_subject', '')}

Draft Email Body:
{assessment.get('draft_email_body', '')}

Discovery Questions:
{assessment.get('discovery_questions', '')}

Research Notes:
{assessment.get('research_notes', '')}

Intent Score: {assessment.get('intent_score', '')}
Intent Signals: {assessment.get('intent_signals', '')}

Gift Card URL: {assessment.get('gift_card_analysis', {}).get('gift_card_url', '')}
Experience Quality: {assessment.get('gift_card_analysis', {}).get('experience_quality', '')}
Has Gift Cards: {assessment.get('gift_card_analysis', {}).get('has_gift_cards', '')}
Corporate Gifting: {assessment.get('gift_card_analysis', {}).get('corporate_gifting', '')}
Balance Checker: {assessment.get('gift_card_analysis', {}).get('balance_checker', '')}
License States: {assessment.get('company_profile', {}).get('license_states', '')}
Operator Type: {assessment.get('company_profile', {}).get('operator_type', '')}

Technology:
POS System: {assessment.get('technology', {}).get('pos_system', '')}
Ecommerce Platform: {assessment.get('technology', {}).get('ecommerce_platform', '')}
Loyalty Platform: {assessment.get('technology', {}).get('loyalty_platform', '')}

Company Profile:
Years in Business: {assessment.get('company_profile', {}).get('years_in_business', '')}
Locations: {assessment.get('company_profile', {}).get('locations', '')}
Revenue: {assessment.get('company_profile', {}).get('revenue_range', '')}"""

    payload = {
        "properties": {
            "hs_task_subject": f"Follow up: {company['name']} — {assessment.get('fit_score', '')} lead",
            "hs_task_body": notes,
            "hs_task_status": "NOT_STARTED",
            "hs_task_type": "EMAIL",
            "hs_timestamp": str(int(time.time() * 1000 + 86400000)),
            "hubspot_owner_id": rep_id
        },
        "associations": [
            {
                "to": {"id": contact_id},
                "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 204}]
            }
        ]
    }

    response = requests.post(
        "https://api.hubapi.com/crm/v3/objects/tasks",
        headers={
            "Authorization": f"Bearer {HUBSPOT_API_KEY}",
            "Content-Type": "application/json"
        },
        json=payload
    )

    if response.status_code in [200, 201]:
        log.info(f"HubSpot task created for {contact.get('name')}")
    else:
        log.error(f"HubSpot task creation failed: {response.text}")

def find_hubspot_company(company_name):
    """Search HubSpot for a company by exact name match. Returns company_id or None."""
    if not company_name:
        return None

    payload = {
        "filterGroups": [{
            "filters": [{
                "propertyName": "name",
                "operator": "EQ",
                "value": company_name
            }]
        }],
        "limit": 1
    }

    response = requests.post(
        "https://api.hubapi.com/crm/v3/objects/companies/search",
        headers={
            "Authorization": f"Bearer {HUBSPOT_API_KEY}",
            "Content-Type": "application/json"
        },
        json=payload
    )

    if response.status_code != 200:
        log.error(f"HubSpot company search failed for {company_name}: {response.text}")
        return None

    results = response.json().get('results', [])
    return results[0]['id'] if results else None

def get_associated_object_ids(from_object_type, object_id, to_object_type):
    """Get IDs of objects associated with a HubSpot object (v4 associations API)"""
    response = requests.get(
        f"https://api.hubapi.com/crm/v4/objects/{from_object_type}/{object_id}/associations/{to_object_type}",
        headers={"Authorization": f"Bearer {HUBSPOT_API_KEY}"}
    )

    if response.status_code != 200:
        log.error(f"HubSpot associations lookup failed for {from_object_type}/{object_id} -> {to_object_type}: {response.text}")
        return []

    return [r['toObjectId'] for r in response.json().get('results', [])]

def get_object_properties(object_type, object_id, properties):
    """Fetch specific properties for a HubSpot object"""
    response = requests.get(
        f"https://api.hubapi.com/crm/v3/objects/{object_type}/{object_id}",
        headers={"Authorization": f"Bearer {HUBSPOT_API_KEY}"},
        params={"properties": ",".join(properties)}
    )

    if response.status_code != 200:
        log.error(f"HubSpot property fetch failed for {object_type}/{object_id}: {response.text}")
        return {}

    return response.json().get('properties', {})

# Deal stage values that count as "closed" — no need to pursue further
CLOSED_DEAL_STAGES = {"closedwon", "closedlost", "77738423"}

# How recent counts as "sales rep already working this" for an open deal
ACTIVITY_RECENCY_DAYS = 60

def company_deal_status_blocks_research(company_id, company_name, contact_ids=None):
    """Check deals associated with the company. Deals may be linked directly to
    the company record, or only to a contact (common when a deal is created
    without an explicit company association) — both sources are checked.
    - Any deal in a closed stage -> block further research.
    - An open deal where the company was last modified within the last
      ACTIVITY_RECENCY_DAYS days -> block (rep is already engaged).
    - No deals, or an open deal with no recent activity -> don't block."""
    deal_ids = set(get_associated_object_ids("companies", company_id, "deals"))

    for contact_id in (contact_ids or []):
        deal_ids.update(get_associated_object_ids("contacts", contact_id, "deals"))

    if not deal_ids:
        log.info(f"{company_name} has no associated deals (checked company and contact associations)")
        return False

    has_open_deal = False
    for deal_id in deal_ids:
        props = get_object_properties("deals", deal_id, ["dealstage", "hs_is_closed"])
        stage = props.get('dealstage', '')
        # hs_is_closed is HubSpot's own computed flag — true for any closed-won/
        # closed-lost stage regardless of pipeline or custom stage IDs. Also check
        # the explicit stage ID list as a backup for edge cases.
        is_closed = str(props.get('hs_is_closed', '')).lower() == 'true' or stage in CLOSED_DEAL_STAGES
        if is_closed:
            log.info(f"{company_name} has a closed deal (stage: {stage}, hs_is_closed: {props.get('hs_is_closed')}) — skipping")
            return True
        has_open_deal = True

    if has_open_deal:
        props = get_object_properties("companies", company_id, ["hs_lastmodifieddate"])
        last_modified = props.get('hs_lastmodifieddate', '')
        if last_modified:
            try:
                last_modified_dt = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
                cutoff = datetime.now(timezone.utc) - timedelta(days=ACTIVITY_RECENCY_DAYS)
                if last_modified_dt >= cutoff:
                    log.info(f"{company_name} has an open deal with activity within {ACTIVITY_RECENCY_DAYS} days (last modified: {last_modified}) — skipping, rep already engaged")
                    return True
            except ValueError:
                log.error(f"Could not parse hs_lastmodifieddate for {company_name}: {last_modified}")

    return False

def company_has_contact_and_task(company_name):
    """Check HubSpot for an existing company that already has an associated contact with an associated task"""
    company_id = find_hubspot_company(company_name)
    if not company_id:
        return False

    contact_ids = get_associated_object_ids("companies", company_id, "contacts")
    if not contact_ids:
        log.info(f"{company_name} exists in HubSpot (ID: {company_id}) but has no associated contacts")
        return False

    for contact_id in contact_ids:
        task_ids = get_associated_object_ids("contacts", contact_id, "tasks")
        if task_ids:
            log.info(f"{company_name} already exists in HubSpot with contact {contact_id} and task {task_ids[0]} — skipping")
            return True

    log.info(f"{company_name} exists in HubSpot with contact(s) but no associated task — checking deal status")
    if company_deal_status_blocks_research(company_id, company_name, contact_ids):
        return True

    log.info(f"{company_name} — no blocking deal status found — proceeding with research")
    return False

def process_company(company):
    """Full pipeline for one company with error handling"""
    company_name = company.get('name', 'Unknown')

    try:
        # Step 0 — Skip if company already exists in HubSpot with a contact and task
        if company_has_contact_and_task(company_name):
            return 'exists'

        # Step 1 — Manus research
        task_id = create_manus_task(company)

        # Step 2 — Poll until complete
        research = poll_manus_until_complete(task_id, timeout=900)

        # Step 3 — Claude qualification
        assessment = claude_qualify(company, research)

        # Step 4 — Check fit score
        if not assessment.get('fit_score'):
            log.error(f"Skipping {company_name} — fit score missing")
            return False

        log.info(f"{company_name} scored {assessment['fit_score']} — creating HubSpot records")

        # Get rep ONCE per company — both contacts go to same rep
        rep_id = get_rep_for_company(company)

        # Step 5 — Create Contact 1 (from Apollo — always)
        contact_1 = assessment['decision_makers'][0]
        contact_id_1 = create_hubspot_contact(contact_1, assessment, company, rep_id)
        if contact_id_1:
            create_hubspot_task(contact_id_1, contact_1, assessment, company, rep_id)

        # Step 6 — Create Contact 2 (from Manus — only if found)
        second = assessment.get('second_contact', {})
        if second.get('found') and second.get('name'):
            log.info(f"Second contact found: {second['name']} — creating HubSpot record")
            #rep_id = get_next_rep()
            contact_id_2 = create_hubspot_contact(second, assessment, company, rep_id)
            if contact_id_2:
                create_hubspot_task(contact_id_2, second, assessment, company, rep_id)
        else:
            log.info(f"No second contact found for {company_name} — skipping")

        return True

    except Exception as e:
        log.error(f"Failed to process {company_name}: {str(e)}")
        return False

# --- MAIN ---
if __name__ == "__main__":
    log.info("SDR Agent starting...")

    filename = 'birchmount-apollo-contacts.csv'
    companies, all_rows = get_unprocessed_companies(filename, limit=30)

    log.info(f"Found {len(companies)} unprocessed companies")

    success_count = 0
    error_count = 0
    exists_count = 0

    for company in companies:
        result = process_company(company)
        if result == 'exists':
            exists_count += 1
            mark_company_processed(filename, all_rows, company['row_index'], status='Exists')
        elif result:
            success_count += 1
            mark_company_processed(filename, all_rows, company['row_index'], status='done')
        else:
            error_count += 1

    log.info(f"Run complete — {success_count} succeeded, {exists_count} already existed, {error_count} failed")
