"""
TANADI AI SAVINGS ASSISTANT v9
pip install flask requests
Edit tanadi_config.py with your keys
python tanadi_app.py  ->  http://127.0.0.1:5000
"""
import requests, datetime, json, os, sys
from flask import Flask, request, jsonify, render_template_string

_dir = os.path.dirname(os.path.abspath(__file__))
_KEY_CACHE = {"ak": "", "ps": "", "loaded": False}

def load_keys():
    """Read tanadi_config.py from multiple locations. Cached but re-reads each call."""
    ak = ""; ps = ""
    paths_to_try = []
    try: paths_to_try.append(_dir)
    except: pass
    paths_to_try += [
        "/storage/emulated/0/Download",
        "/sdcard/Download",
        "/sdcard",
        os.path.expanduser("~"),
    ]
    try: paths_to_try.append(os.getcwd())
    except: pass

    for folder in paths_to_try:
        try:
            cfg = os.path.join(folder, "tanadi_config.py")
            if not os.path.exists(cfg):
                continue
            with open(cfg, "r", errors="ignore") as f:
                for raw in f:
                    line = raw.strip().rstrip(";").strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        parts = line.split("=", 1)
                        k = parts[0].strip()
                        v = parts[1].strip().strip('"').strip("'").rstrip(";").strip()
                        if k == "ANTHROPIC_KEY" and len(v) > 10:
                            ak = v
                        elif k == "PAYSTACK_SECRET" and len(v) > 10:
                            ps = v
                        elif k == "GROQ_KEY" and len(v) > 10:
                            _KEY_CACHE["groq"] = v
                        elif k == "TOGETHER_KEY" and len(v) > 10:
                            _KEY_CACHE["together"] = v
                        elif k == "GEMINI_KEY" and len(v) > 10:
                            _KEY_CACHE["gemini"] = v
            break  # stop at first found config
        except Exception:
            continue
    _KEY_CACHE["ak"] = ak
    _KEY_CACHE["ps"] = ps
    _KEY_CACHE["loaded"] = True
    return ak, ps

# Load at startup
ANTHROPIC_KEY, PAYSTACK_SECRET = load_keys()

def get_keys():
    return load_keys()

def get_groq_key():
    load_keys()
    return _KEY_CACHE.get("groq","")

def get_together_key():
    load_keys()
    return _KEY_CACHE.get("together","")

def get_gemini_key():
    load_keys()
    return _KEY_CACHE.get("gemini","")

def has_ps():
    try:
        _, ps = get_keys()
        return bool(ps) and ps.startswith("sk_") and len(ps) > 10
    except:
        return False

def has_ant():
    try:
        ak, _ = get_keys()
        return bool(ak) and ak.startswith("sk-ant-")
    except:
        return False

app = Flask(__name__)
PS = "https://api.paystack.co"

store = {
    "vault": {"balance": 0.0, "transactions": []},
    "ml_memory": [],
    "chat_memory": [],
}

ML_B = [
    (2500,3250,11),(3250,4000,55),(4000,4750,143),(4750,5500,285),
    (5500,6250,477),(6250,7000,657),(7000,7750,830),(7750,8500,1042),
    (8500,9250,1205),(9250,10001,1403)
]

def ml(inc, food, tra, air, oth):
    act  = inc - food - tra - air - oth
    pred = inc*.22 - food*.85 - tra*.9 - air*.8 - oth*.75
    rate = (act / inc * 100) if inc > 0 else 0
    if   rate <= 0:  sc = max(0, int(10 + rate*2))
    elif rate <= 5:  sc = int(10 + rate*4)
    elif rate <= 10: sc = int(30 + (rate-5)*4)
    elif rate <= 20: sc = int(50 + (rate-10)*2.5)
    else:            sc = min(100, int(75 + (rate-20)*1.25))
    peer = next((a for lo,hi,a in ML_B if lo<=inc<hi), None)
    tgt  = max(0, int((pred+act)/2)) if act < pred else int(act)
    leak = max([("Food",food),("Transport",tra),("Airtime",air),("Other",oth)], key=lambda x:x[1])[0]
    return dict(actual=round(act,2), ideal=round(max(0,pred),2), rate=round(rate,1),
                score=sc, target=tgt, peer_avg=peer, leak=leak)

SYSTEM = """You are Tanadi, an advanced AI assistant built for Nigerian users - like having ChatGPT, Grok, and a financial advisor in one app.

You are highly intelligent, knowledgeable, and conversational. You can discuss ANY topic.

YOUR CAPABILITIES:
- Understand natural human conversation in any language (English, Pidgin, Hausa, Yoruba, Igbo, French, Arabic, etc.)
- Answer questions from ALL fields: science, technology, AI, programming, business, economics, health, education, history, culture, relationships, entertainment, sports, and more
- Explain complex ideas in simple language
- Provide step-by-step solutions when needed
- Analyse budgets and give Nigerian-specific financial advice
- Maintain conversation context and understand follow-up questions

BEHAVIOR RULES:
1. Always respond clearly, intelligently, and helpfully
2. For complex questions, break answers into simple steps
3. Be polite, warm, and encouraging at all times
4. Give examples to improve understanding when helpful
5. If asked about real-time data (weather, prices, news), explain you lack live data but provide relevant context
6. Support any language - respond in the same language the user writes in
7. Never refuse a reasonable question

NIGERIAN FINANCIAL DATA (use when analysing budgets):
- Average income: N6,277/month, Average savings: N617 (9.8%)
- Income N2,500-4,000: avg save N11/month
- Income N4,000-6,000: avg save N143-477/month  
- Income N6,000-8,000: avg save N657-1,042/month
- Income N8,000-10,000: avg save N1,205-1,403/month
- Food = avg 32% of income, Transport = avg 16%
- 1 in 5 Nigerians saves nothing each month
- Always use N for naira (e.g. N5,000)

For budget analysis respond with:
SCORE: [X]/100
YOUR SAVINGS: N[amount] ([rate]%)
RECOMMENDED: N[amount]/month (20% rule)
PEERS: [how they compare to similar earners]
TIP: [one specific actionable advice]

Your goal: help users solve problems, learn new things, and get accurate information quickly. Prioritize accuracy, clarity, and usefulness in every response. Keep replies under 200 words unless a detailed explanation is needed."""

def ps_h():
    _, ps = get_keys()
    return {"Authorization": f"Bearer {ps}", "Content-Type": "application/json"}

def ps_banks():
    try:
        r = requests.get(f"{PS}/bank?country=nigeria&perPage=100", headers=ps_h(), timeout=15)
        d = r.json()
        if d.get("status"):
            return [{"name": b["name"], "code": b["code"]} for b in d["data"]]
    except: pass
    return []

def ps_verify(acct, code):
    try:
        r = requests.get(f"{PS}/bank/resolve?account_number={acct}&bank_code={code}",
                         headers=ps_h(), timeout=15)
        d = r.json()
        if d.get("status"):
            return {"ok": True, "name": d["data"]["account_name"], "number": d["data"]["account_number"]}
        return {"ok": False, "msg": d.get("message", "Verification failed")}
    except Exception as e:
        return {"ok": False, "msg": str(e)}

def ps_balance():
    try:
        r = requests.get(f"{PS}/balance", headers=ps_h(), timeout=15)
        d = r.json()
        if d.get("status"):
            bal = sum(c["balance"] for c in d["data"] if c.get("currency") == "NGN")
            return {"ok": True, "balance": round(bal/100, 2)}
        return {"ok": False, "msg": d.get("message", "Cannot fetch balance")}
    except Exception as e:
        return {"ok": False, "msg": str(e)}

def ps_transfer(amount, acct, bank_code, bank_name, acct_name, reason):
    try:
        rc = requests.post(f"{PS}/transferrecipient", headers=ps_h(),
            json={"type":"nuban","name":acct_name,"account_number":acct,
                  "bank_code":bank_code,"currency":"NGN"}, timeout=15)
        rd = rc.json()
        if not rd.get("status"):
            return {"ok": False, "msg": rd.get("message", "Recipient creation failed")}
        code = rd["data"]["recipient_code"]
        tr = requests.post(f"{PS}/transfer", headers=ps_h(),
            json={"source":"balance","amount":int(amount*100),"recipient":code,"reason":reason},
            timeout=15)
        td = tr.json()
        if td.get("status"):
            return {"ok": True, "ref": td["data"].get("reference",""), "status": td["data"].get("status","pending")}
        return {"ok": False, "msg": td.get("message","Transfer failed")}
    except Exception as e:
        return {"ok": False, "msg": str(e)}

def ps_init_payment(amount, email, ref):
    try:
        r = requests.post(f"{PS}/transaction/initialize", headers=ps_h(),
            json={"email":email,"amount":int(amount*100),"reference":ref,"currency":"NGN",
                  "callback_url":"http://127.0.0.1:5000/payment-callback"}, timeout=15)
        d = r.json()
        if d.get("status"):
            return {"ok": True, "url": d["data"]["authorization_url"], "ref": ref}
        return {"ok": False, "msg": d.get("message","Init failed")}
    except Exception as e:
        return {"ok": False, "msg": str(e)}

def ps_verify_payment(ref):
    try:
        r = requests.get(f"{PS}/transaction/verify/{ref}", headers=ps_h(), timeout=15)
        d = r.json()
        if d.get("status") and d["data"]["status"] == "success":
            return {"ok": True, "amount": d["data"]["amount"]/100, "ref": ref}
        return {"ok": False, "msg": "Payment not completed yet. Try again."}
    except Exception as e:
        return {"ok": False, "msg": str(e)}

FALLBACK_BANKS = [
    {"name":"GTBank","code":"058"},{"name":"Access Bank","code":"044"},
    {"name":"First Bank of Nigeria","code":"011"},{"name":"UBA","code":"033"},
    {"name":"Zenith Bank","code":"057"},{"name":"Fidelity Bank","code":"070"},
    {"name":"Sterling Bank","code":"232"},{"name":"Union Bank","code":"032"},
    {"name":"Ecobank Nigeria","code":"050"},{"name":"Stanbic IBTC","code":"221"},
    {"name":"OPay","code":"999992"},{"name":"PalmPay","code":"999991"},
    {"name":"Kuda Bank","code":"090267"},{"name":"Moniepoint MFB","code":"090405"},
    {"name":"Carbon","code":"565"},{"name":"Wema Bank","code":"035"},
    {"name":"9PSB","code":"120001"},{"name":"Polaris Bank","code":"076"},
    {"name":"Heritage Bank","code":"030"},{"name":"Keystone Bank","code":"082"},
]

# ===================== JS FALLBACK BRAIN =====================
JS_BRAIN = """
function jsReply(msg){
  var m=(msg||'').toLowerCase().trim();
  var orig=msg||'';

  // --- GREETINGS ---
  if(/\b(hi|hello|hey|good morning|good afternoon|good evening|yo|sup|howdy)\b/.test(m))
    return "Hello! I am Tanadi, your advanced AI assistant. Ask me anything - savings, health, science, technology, history, relationships, coding, or any topic at all. What would you like to explore?";
  if(/\b(how are you|how r u|you good|how do you do|are you okay|how are things)\b/.test(m))
    return "I am doing great, thank you for asking! Ready to help with anything on your mind. How are YOU doing today?";
  if(/\b(thank|thanks|thank you|thx|cheers|appreciate)\b/.test(m))
    return "You are very welcome! Always here to help. Keep saving and keep learning!";
  if(/\b(bye|goodbye|see you|take care|later|good night|good night)\b/.test(m))
    return "Goodbye! Every naira saved today builds your tomorrow. Come back anytime!";
  if(/\b(joke|funny|make me laugh|tell me something funny|humor)\b/.test(m))
    return "Why did the naira go to therapy? It had too many cents of self-doubt! On a serious note though - building savings is the best joke you can play on financial stress. What else can I help with?";

  // --- IDENTITY ---
  if(/\b(who are you|what are you|what is tanadi|about yourself|what can you do|your name|introduce yourself)\b/.test(m))
    return "I am Tanadi - an advanced AI assistant built for Nigerian users! I have knowledge in science, technology, AI, programming, business, economics, health, education, world history, culture, finance, relationships, and much more. I speak English, Pidgin, Hausa, Yoruba, and Igbo. Think of me as your personal AI for any topic. What would you like to know?";

  // --- LOVE AND RELATIONSHIPS ---
  if(/\b(what is love|about love|define love|explain love|meaning of love|love mean|types of love|information about love|love and|love in)\b/.test(m))
    return "Love is a deep emotional bond and attachment between people. Psychologists identify several types: (1) Romantic love - passionate attraction between partners. (2) Familial love - the bond between family members. (3) Friendship love - deep care for close friends. (4) Self-love - healthy appreciation and respect for yourself. (5) Unconditional love - love with no conditions attached. Psychologist Robert Sternberg's theory says love has three components: Intimacy (closeness), Passion (attraction), and Commitment (decision to stay). Healthy love involves mutual respect, trust, communication, and support. In Nigerian culture, love also includes responsibility, loyalty to family, and community values.";
  if(/\b(relationship|dating|marriage|partner|girlfriend|boyfriend|husband|wife|romance|romantic)\b/.test(m))
    return "Healthy relationships are built on: (1) Honest communication - talk openly about feelings and needs. (2) Mutual respect - value each other's opinions and boundaries. (3) Trust - be reliable and faithful. (4) Support - be there during good and bad times. (5) Independence - maintain your own identity and friendships. In Nigeria, relationships also involve family acceptance and shared values. Red flags to avoid: controlling behavior, lack of respect, constant dishonesty, and emotional manipulation.";
  if(/\b(i love you|do you love me|love you|do you like me)\b/.test(m))
    return "I care deeply about every user I help! While I am an AI, I genuinely want the best for you - financially, mentally, and in all areas of life. What is on your mind today?";

  // --- INSURANCE ---
  if(/\b(life insurance|insurance|define.*insurance|what is.*insurance|insurance mean|health insurance|car insurance)\b/.test(m)){
    if(/life/.test(m)) return "Life insurance is a contract between you and an insurance company. You pay regular premiums, and if you die, the company pays a lump sum (death benefit) to your chosen beneficiaries (family members). WHY it matters: (1) Protects your family financially if you die unexpectedly. (2) Covers funeral expenses. (3) Pays off debts. (4) Replaces your income for dependants. In Nigeria: AIICO Insurance, Leadway Assurance, and AXA Mansard offer life insurance. NHIS covers basic health insurance. Most policies start from N3,000 per month. Rule of thumb: get coverage worth 10 times your annual income.";
    if(/health/.test(m)) return "Health insurance covers your medical expenses. You pay monthly premiums and the insurer covers hospital bills, drugs, and treatments. In Nigeria: NHIS (National Health Insurance Scheme) is the main government scheme. Private options: Hygeia HMO, Reliance HMO, AXA Mansard Health. Benefits: reduces out-of-pocket hospital costs by up to 80 percent. Many employers provide health insurance. If self-employed, budget N5,000 to N15,000 per month for private HMO.";
    return "Insurance is a financial protection system where you pay regular premiums to an insurance company, and they compensate you if a covered risk occurs. Types in Nigeria: (1) Life insurance - pays family if you die. (2) Health insurance - covers medical bills. (3) Car insurance - required by law, covers accidents. (4) Home insurance - protects your property. (5) Business insurance - covers business losses. Key companies in Nigeria: AIICO, Leadway, AXA Mansard, Cornerstone Insurance. Insurance is one of the most underused financial tools in Nigeria - only about 1 percent of Nigerians are insured!";
  }

  // --- FINANCE AND ECONOMICS ---
  if(/\b(what is.*economy|define.*economy|economy mean|economics|gdp|inflation|recession|currency)\b/.test(m))
    return "Economics is the study of how societies produce, distribute, and consume goods and services. Key concepts: GDP (Gross Domestic Product) = total value of all goods and services a country produces in a year. Nigeria GDP is about 477 billion USD making it Africa's largest economy. Inflation = rise in prices over time - Nigeria currently has high inflation affecting purchasing power. Exchange rate: the value of naira vs other currencies. Interest rate: cost of borrowing money - set by CBN (Central Bank of Nigeria). Understanding economics helps you make smarter financial decisions!";
  if(/\b(invest|investment|treasury bill|piggyvest|cowrywise|stock|shares|nse|mutual fund)\b/.test(m))
    return "Best investments for Nigerians: LOW RISK - Treasury Bills at CBN (18-21% per year), Fixed deposits (10-15%), Money market funds. MEDIUM RISK - Piggyvest and Cowrywise (10-13%), Agricultural investments, Real estate. HIGHER RISK - NSE stocks, Cryptocurrency, Forex trading. GOLDEN RULE: Build a 3-month emergency fund first. Start small - even N5,000 per month invested grows significantly over time. Compound interest is powerful: N10,000/month at 15% annually = N3.5 million after 10 years!";
  if(/\b(save|saving|savings|how much.*save|budget tip|spend less|cut cost)\b/.test(m)&&!/earn|income|salary|naira|[0-9]/.test(m))
    return "The golden savings rule: save 10-20% of your income every month. Practical tips: (1) Pay yourself first - move savings to vault immediately on payday. (2) Track every expense for one week - you will find waste. (3) Reduce eating out - cook at home 5 days a week. (4) Switch to cheaper data bundles. (5) Use USSD banking to avoid transport to bank. (6) Cancel subscriptions you do not use. (7) Buy in bulk at open markets. Tell me your income and expenses for a full personalised analysis!";

  // --- NIGERIAN BANKING AND FINTECH ---
  if(/\b(opay|kuda|palmpay|moniepoint|bank.*app|fintech|ussd|transfer.*bank|banking app)\b/.test(m))
    return "Top Nigerian banking apps: KUDA BANK - zero transfer fees, savings interest up to 15%, fully digital. OPAY - USSD code *955#, works without internet, easy for all ages. PALMPAY - cashback on every transaction, *945#. PIGGYVEST - locks savings away, earns 10-13% interest, great for discipline. MONIEPOINT - excellent for business owners and POS agents. COWRYWISE - investment and savings plans. USSD codes: GTBank *737#, Access *901#, First Bank *894#, UBA *919#, Zenith *966#. All USSD codes work 24/7 without internet!";

  // --- SCIENCE ---
  if(/\b(what is science|define science|explain.*science|science mean)\b/.test(m))
    return "Science is the systematic study of the natural world through observation, experimentation, and evidence. Major branches: Physics - matter, energy, forces. Chemistry - substances and reactions. Biology - living organisms. Astronomy - stars, planets, space. Earth Science - geology, weather, oceans. Mathematics - the language of science. Science gives us medicine, technology, agriculture, and our understanding of the universe. Nigeria has produced notable scientists including Philip Emeagwali who contributed to supercomputer development.";
  if(/\b(what is physics|define physics|explain physics)\b/.test(m))
    return "Physics is the science of matter, energy, space, and time. It explains everything from atoms to galaxies. Key areas: Mechanics (motion and forces), Thermodynamics (heat and energy), Electromagnetism (electricity and magnetism), Quantum mechanics (subatomic particles), Relativity (Einstein's theory of space-time). Everyday applications: phones, cars, electricity, bridges, MRI machines. Newton's three laws of motion form the foundation of classical physics. E=mc2 (Einstein) shows that mass and energy are equivalent.";
  if(/\b(what is chemistry|define chemistry|explain chemistry)\b/.test(m))
    return "Chemistry is the science of matter - what things are made of and how they change. Key branches: Organic chemistry (carbon compounds, medicines), Inorganic chemistry (minerals, metals), Physical chemistry (energy in reactions), Biochemistry (chemistry of living things). The periodic table organises all 118 known elements. Chemistry gives us: medicines, plastics, fuels, food preservation, cleaning products. Important concept: atoms combine to form molecules, which make up everything around us.";
  if(/\b(what is biology|define biology|explain biology)\b/.test(m))
    return "Biology is the science of life and living organisms. Key branches: Botany (plants), Zoology (animals), Microbiology (microorganisms), Genetics (inheritance and DNA), Ecology (organisms and environment), Human biology (the human body). The cell is the basic unit of life - all living things are made of cells. DNA carries the genetic instructions for all living organisms. Evolution by natural selection explains how species developed over billions of years. Biology is fundamental to medicine, agriculture, and environmental science.";

  // --- TECHNOLOGY ---
  if(/\b(what is technology|define technology|explain technology|technology mean)\b/.test(m))
    return "Technology is the application of scientific knowledge to create tools and systems that solve problems and improve life. Types: Information Technology (computers, internet, software), Communication Technology (phones, 5G, satellites), Medical Technology (MRI, vaccines, surgery), Agricultural Technology (irrigation, fertilisers, drones), Energy Technology (solar, wind, nuclear). Nigeria's tech ecosystem: Yaba in Lagos is called Yabacon Valley. Major companies: Flutterwave, Paystack (acquired by Stripe for 200 million USD), Andela, Interswitch. The digital economy offers huge opportunities for Nigerian youth!";
  if(/\b(what is internet|how does internet work|explain internet|internet mean)\b/.test(m))
    return "The internet is a global network of billions of computers and devices connected together, sharing information. How it works: Data is broken into small packets, sent through cables and wireless signals, reassembled at the destination. Key components: Servers (store websites), Routers (direct traffic), IP addresses (unique identifier for each device), HTTP/HTTPS (protocol for websites), DNS (converts website names to IP addresses). Nigeria has over 100 million internet users. 4G LTE is widely available in cities. Fibre optic cables connect Nigeria to global internet infrastructure.";
  if(/\b(what is 5g|explain 5g|5g network|how does 5g)\b/.test(m))
    return "5G is the 5th generation of mobile network technology. It is up to 100 times faster than 4G. Key features: Speed up to 20 Gbps (download a full movie in seconds), Ultra-low latency (near-instant response), Connects millions of devices simultaneously (Internet of Things). Applications: autonomous vehicles, remote surgery, smart cities, virtual reality. In Nigeria: MTN and Mafab Communications have 5G licences. Rollout is starting in major cities like Lagos and Abuja. 5G will transform industries including healthcare, agriculture, and manufacturing.";

  // --- AI AND COMPUTING ---
  if(/\b(what is ai|artificial intelligence|explain ai|how does ai|ai mean|machine learning|deep learning|neural network|chatgpt|gpt|llm)\b/.test(m))
    return "Artificial Intelligence (AI) is computer technology that mimics human thinking and learning. How it works: AI systems are trained on massive datasets - I was trained on billions of texts. Machine Learning is a type of AI where the system learns from examples without being explicitly programmed. Deep Learning uses neural networks (inspired by the human brain) to process complex data. Applications: voice assistants (Siri, Alexa), recommendation systems (Netflix, YouTube), medical diagnosis, self-driving cars, language translation, and assistants like me! Generative AI like ChatGPT and Tanadi can write, explain, analyse, and answer questions on any topic.";
  if(/\b(what is blockchain|explain blockchain|cryptocurrency|bitcoin|ethereum|crypto|web3)\b/.test(m))
    return "Blockchain is a distributed digital ledger that records transactions across many computers. Key features: Decentralised (no single owner), Transparent (anyone can verify), Immutable (records cannot be changed). Cryptocurrency is digital money built on blockchain: Bitcoin (BTC) - first and largest crypto. Ethereum (ETH) - smart contracts platform. Uses beyond crypto: supply chain tracking, digital identity, land registration, healthcare records. In Nigeria, crypto adoption is among the highest in the world despite CBN restrictions. Always be cautious - crypto is highly volatile and unregulated. Never invest more than you can afford to lose.";

  // --- CODING ---
  if(/\b(programming|coding|how to code|learn.*programming|python|javascript|java|html|css|software|developer|computer science)\b/.test(m))
    return "Learning to code is one of the best career investments you can make! Most in-demand skills 2025: Python (AI, data science, automation), JavaScript (web development), React (frontend apps), SQL (databases), Cloud computing (AWS, Azure). Free learning resources: freeCodeCamp.org (web dev, Python, SQL), python.org (official Python tutorials), Harvard CS50 on YouTube (completely free!), Khan Academy (for beginners). Nigerian coding bootcamps: Semicolon Africa (Lagos), Decagon Institute, AltSchool Africa, Andela. Entry-level developer salary in Nigeria: N150,000 to N500,000 per month. Remote work opportunities available globally!";

  // --- HEALTH ---
  if(/\b(what is diabetes|explain diabetes|diabetes mean|blood sugar|type 1|type 2)\b/.test(m))
    return "Diabetes is a chronic condition where the body cannot properly regulate blood sugar (glucose) levels. Type 1: immune system attacks insulin-producing cells - requires daily insulin injections. Type 2: body becomes resistant to insulin - most common type, often lifestyle-related. Symptoms: frequent urination, excessive thirst, blurred vision, slow healing wounds, fatigue. Prevention of Type 2: reduce sugar and refined carbohydrates, exercise 30 minutes daily, maintain healthy weight, avoid sugary drinks. Management: medication, diet control, regular blood sugar monitoring. Nigeria has over 3 million people living with diabetes. See a doctor if you have symptoms!";
  if(/\b(what is malaria|explain malaria|malaria symptom|malaria treatment|prevent malaria)\b/.test(m))
    return "Malaria is a life-threatening disease caused by Plasmodium parasites transmitted through infected female Anopheles mosquito bites. Symptoms: high fever, chills and shaking, headache, muscle pain, vomiting, fatigue. Treatment: Artemisinin-based Combination Therapy (ACT) like Coartem or Lonart. Take full course even when feeling better! Prevention: sleep under insecticide-treated nets, use mosquito repellent, eliminate stagnant water near home, take prophylaxis if travelling to high-risk areas. Nigeria accounts for about 27% of global malaria cases. Seek treatment within 24 hours of symptoms - malaria can be fatal if untreated!";
  if(/\b(what is hiv|hiv aids|explain hiv|prevent hiv|aids treatment)\b/.test(m))
    return "HIV (Human Immunodeficiency Virus) is a virus that attacks the immune system. AIDS (Acquired Immunodeficiency Syndrome) is the advanced stage of HIV infection. Transmission: unprotected sexual contact, sharing needles, mother to child during birth or breastfeeding. NOT transmitted by: casual contact, hugging, sharing food, coughing. Prevention: use condoms consistently, avoid sharing needles, PrEP medication for high-risk individuals, mother-to-child prevention programs. Treatment: Antiretroviral Therapy (ART) - HIV-positive people who take ART consistently can live long healthy lives and have an undetectable viral load meaning they cannot transmit the virus. Get tested regularly - early detection saves lives. LUTH and major hospitals offer free HIV testing.";
  if(/\b(what is cancer|explain cancer|cancer treatment|cancer prevention|types of cancer)\b/.test(m))
    return "Cancer occurs when cells in the body grow uncontrollably, forming tumours or spreading through the bloodstream. Common types in Nigeria: Breast cancer (most common in women - self-examine monthly), Cervical cancer (preventable with HPV vaccine), Prostate cancer (common in men over 50), Colorectal cancer, Leukaemia (blood cancer). Warning signs: unexplained weight loss, persistent cough, unusual lumps, abnormal bleeding, chronic pain. Prevention: avoid tobacco and alcohol, eat fruits and vegetables, exercise regularly, get regular screenings. Treatment: surgery, chemotherapy, radiation therapy, immunotherapy. Early detection greatly improves survival rates - do not ignore symptoms!";
  if(/\b(mental health|depression|anxiety|stress|emotional|psychological|therapy|counselling)\b/.test(m))
    return "Mental health is just as important as physical health! Common conditions: Depression - persistent sadness, loss of interest, hopelessness. Anxiety - excessive worry, panic attacks, fear. PTSD - trauma responses. Signs you need help: sleeping too much or too little, withdrawing from people, feeling hopeless for weeks, inability to function normally. Healthy habits: exercise releases mood-boosting endorphins, talk to trusted people, limit social media, practice gratitude, get adequate sleep (7-8 hours). Professional help: LASUTH psychiatry department, NIMH (National Institute for Mental Health in Sabongida-Ora), Mentally Aware Nigeria Initiative (MANI). Seeking help is a sign of strength, not weakness!";
  if(/\b(what is blood pressure|high blood pressure|hypertension|low blood pressure|blood pressure mean)\b/.test(m))
    return "Blood pressure is the force of blood pushing against artery walls. Measured as two numbers: Systolic (top number) - pressure when heart beats. Diastolic (bottom number) - pressure between beats. Normal: 120/80 mmHg. High blood pressure (hypertension): above 140/90 mmHg - damages heart, kidneys, brain. LOW blood pressure: below 90/60 mmHg - causes dizziness. Hypertension prevention: reduce salt intake (use less Maggi and seasoning cubes), exercise 30 minutes daily, maintain healthy weight, limit alcohol, manage stress, avoid smoking. Many Nigerians have undiagnosed hypertension - check yours at any pharmacy for free. Take medications as prescribed without stopping!";

  // --- EDUCATION ---
  if(/\b(what is.*education|define education|explain education|importance of education|why.*education)\b/.test(m))
    return "Education is the process of acquiring knowledge, skills, values, and understanding through learning and experience. Types: Formal (school, university), Non-formal (vocational training, adult literacy), Informal (life experiences, self-learning). Importance: (1) Opens career opportunities. (2) Increases earning potential - graduates earn 2-3x more on average. (3) Develops critical thinking. (4) Reduces poverty. (5) Drives national development. Education in Nigeria: 6 years primary (ages 6-12), 6 years secondary (JSS and SSS), 4-6 years university. Online learning has revolutionised access - Coursera, edX, Khan Academy, and YouTube offer world-class free education. Lifelong learning is the key to success in the modern world!";

  // --- HISTORY ---
  if(/\b(nigeria.*history|history.*nigeria|nigeria independent|when.*nigeria|colonialism.*nigeria)\b/.test(m))
    return "Nigeria's history: Ancient kingdoms - Nok civilisation (500 BC), Benin Kingdom (13th century), Kanem-Bornu Empire, Oyo Empire, Sokoto Caliphate. Colonial era: British colonisation began in the 1800s. 1914 - Lord Lugard amalgamated Northern and Southern Nigeria. Independence: October 1, 1960 - Nigeria gained independence from Britain. First Republic under Tafawa Balewa. Civil War: 1967-1970, the Biafran War caused immense loss. Military rule dominated from 1966-1999 with brief civilian periods. Democracy returned in 1999. Current constitution: 1999. Nigeria now has 36 states and Abuja as FCT capital. Nigeria has produced Nobel Laureate Wole Soyinka (1986), the first Black African to win the Nobel Prize in Literature.";
  if(/\b(world war|ww1|ww2|world war 1|world war 2|second world war|first world war|hitler|nazi)\b/.test(m)){
    if(/1|one|first|ww1/.test(m)) return "World War 1 (1914-1918): Triggered by assassination of Archduke Franz Ferdinand of Austria-Hungary in Sarajevo. Major sides: Allied Powers (Britain, France, Russia, USA) vs Central Powers (Germany, Austria-Hungary, Ottoman Empire). Key features: trench warfare, chemical weapons, 20 million deaths. Ended with Treaty of Versailles (1919) which punished Germany heavily. Consequences: collapse of 4 empires, redrawing of world map, harsh conditions on Germany that contributed to WW2. Nigeria fought for Britain - Nigerian soldiers served in East Africa and Europe.";
    return "World War 2 (1939-1945): Started when Hitler's Nazi Germany invaded Poland. Allied Powers (UK, France, USA, Soviet Union) vs Axis Powers (Germany, Italy, Japan). Key events: Battle of Britain, Holocaust (6 million Jews murdered), D-Day invasion, atomic bombs on Hiroshima and Nagasaki. Death toll: 70-85 million people. Ended August 1945. Consequences: United Nations formed, start of Cold War, decolonisation of Africa and Asia, Israel established, Marshall Plan rebuilt Europe. Nigerian soldiers served with British forces in Burma and other theatres.";
  }

  // --- ENVIRONMENT ---
  if(/\b(climate change|global warming|greenhouse|carbon|environment|pollution|renewable|solar energy|deforestation)\b/.test(m))
    return "Climate change is the long-term shift in global temperatures and weather patterns, primarily caused by human activities since the industrial revolution. Main cause: burning fossil fuels (coal, oil, gas) releases CO2 - a greenhouse gas that traps heat. Effects on Nigeria: increased flooding in coastal cities (Lagos, Port Harcourt), desertification in the north (Lake Chad is shrinking), more extreme heat and unpredictable rainfall affecting farmers. Solutions: renewable energy (Nigeria has excellent solar potential - 6 hours of sunshine daily on average), reforestation, sustainable agriculture, reducing waste. Individual actions: reduce plastic use, conserve electricity, use public transport. Nigeria signed the Paris Agreement committing to reduce emissions.";

  // --- BUSINESS AND ENTREPRENEURSHIP ---
  if(/\b(business|how to start|entrepreneurship|startup|small business|side hustle|make money|earn more)\b/.test(m))
    return "Starting a business in Nigeria: STEP 1 - Find a real problem your community faces. STEP 2 - Validate your idea (ask 10 potential customers if they would pay for it). STEP 3 - Start lean - begin small, keep costs low, test quickly. STEP 4 - Register with CAC (Corporate Affairs Commission) for credibility. STEP 5 - Market through WhatsApp, Instagram, and Facebook (free and effective in Nigeria). STEP 6 - Track income and expenses from day one. Support available: Tony Elumelu Foundation (free N5 million seed capital), Bank of Industry loans, NIRSAL MFB, Youth Investment Fund. Common successful Nigerian businesses: food/catering, fashion, logistics, agribusiness, tech services, education.";

  // --- LANGUAGES ---
  if(/\b(sannu|nagode|lafiya|kudi|yaya|ina kwana|sai anjima)\b/.test(m))
    return "Sannu da zuwa! Ni Tanadi ne, mataimakiyar AI. Zan iya amsa tambayoyi kan kuɗi, ilimi, lafiya, kimiyya, fasaha, da duk wani batu. Menene kuke son sani yau?";
  if(/\b(bawo|jowo|ese|owo|pele|eku|orire|e kaabo|ẹ kaabọ)\b/.test(m))
    return "E kaabo! Emi ni Tanadi, oluranlowo AI rẹ. Mo le ran ẹ lọwọ pẹlu owo, ilera, imọ-jinlẹ, imọ-ẹrọ, ati ohunkohun ti o fẹ mọ. Kilo fẹ sọrọ loni?";
  if(/\b(kedu|ndewo|daalu|ego|ezigbo|nnoo|i bialatara)\b/.test(m))
    return "Ndewo! Abu m Tanadi, onye enyemaka AI. Enwere m ike inyere gi aka na ihe niile - ego, ahụike, sayensị, teknọlọjị, na ihe ọ bụla ọzọ. Gwa m ihe ọ bụla i chọrọ ịmara!";
  if(/\b(abeg|wetin|shey|wahala|oya|dey|na im|no be|waka|na wa|e don)\b/.test(m))
    return "Ehen! Na me be Tanadi - your intelligent AI wey sabi everything! I fit help you with money, health, school, business, science, history, or any topic wey dey your mind. Wetin you wan discuss?";

  // --- BUDGET ANALYSIS (with numbers) ---
  var nums=m.match(/[0-9][0-9,]*/g)||[];
  var amounts=nums.map(function(n){return parseInt(n.replace(/,/g,''));}).filter(function(n){return n>100;});
  if(amounts.length>=2&&/earn|income|salary|spend|spent|food|transport|naira|n[0-9]/.test(m)){
    var inc=amounts[0];
    var spent=amounts.slice(1).reduce(function(a,b){return a+b;},0);
    var saved=inc-spent;
    var rate=inc>0?Math.round(saved/inc*1000)/10:0;
    var grade=rate>=20?'Excellent':rate>=10?'Good':rate>=5?'Fair':'Needs Work';
    var comp=inc<=4000?'bottom 20% of earners':inc<=6000?'below average earners':inc<=8000?'average earners':inc<=10000?'above average earners':'top earners in our study';
    return 'Savings Analysis: SCORE: '+grade+' | Your savings: N'+Math.max(0,saved).toLocaleString()+' ('+Math.max(0,rate)+'%) | Recommended: N'+Math.round(inc*0.2).toLocaleString()+'/month (20% rule) | You are among '+comp+'. Tip: '+(rate>=20?'Excellent discipline! Consider putting surplus in Treasury Bills for 18-21% annual returns.':rate>=10?'Good progress! Try to reach 20% by reducing one expense category this month.':'Try the pay-yourself-first method: move savings to vault immediately on payday before spending anything.');
  }

  // --- GENERAL QUESTION HANDLER (what is X, define X, explain X) ---
  var whatIs=m.match(/^(?:what is|what are|define|explain|describe|meaning of|tell me about|information about|i need.*about|about)\s+(.+)$/);
  if(whatIs){
    var topic=whatIs[1].replace(/[?!.,]+$/,'').trim();
    if(topic.length>0){
      var topicWords=topic.split(/\s+/).slice(0,4).join(' ');
      // Actually answer based on topic keyword
      var tl=topicWords.toLowerCase();
      if(/love|relationship|marriage|dating/.test(tl)) return "Love is a deep emotional bond between people. Psychologists identify types: Romantic love (passionate attraction), Familial love (family bonds), Friendship love (philia), Self-love (philautia), Unconditional love (agape). In Nigerian context, love in marriage includes family acceptance, shared values, and mutual respect. Love is both a feeling and a choice — it grows with time and effort.";
      if(/science/.test(tl)) return "Science is the systematic study of the natural world through observation and experiment. Main branches: Natural Science (Physics, Chemistry, Biology, Astronomy), Social Science (Economics, Psychology), Applied Science (Engineering, Medicine). Science works through: Observe, Question, Hypothesize, Experiment, Analyse, Conclude. Nigeria has produced great scientists like Prof. Philip Emeagwali (supercomputing pioneer).";
      if(/noun|verb|adjective|adverb|grammar|english/.test(tl)) return "Grammar is the set of rules for using a language correctly. Parts of speech: Noun (names things — Lagos, girl, love), Verb (action/state — run, is, think), Adjective (describes noun — big, beautiful), Adverb (modifies verb — quickly, very), Pronoun (replaces noun — he, she, they), Preposition (shows position — in, on, at), Conjunction (connects — and, but, or). Ask me about any specific part of speech for a full explanation!";
      if(/security/.test(tl)) return "Security means protection from harm or loss. Types: Personal security (physical safety), Financial security (savings + emergency fund), Cybersecurity (protecting data online), National security (protecting a country), Food security (reliable access to food). Financial security tip: Build a 3-month emergency fund = your biggest financial shield!";
      if(/tanadi/.test(tl)) return "I am Tanadi — your AI assistant built for Nigerian users! I combine savings intelligence with general knowledge. I can help with: budget analysis and savings tips, any knowledge topic (science, health, tech, history), Nigerian banking and culture, conversation in English, Pidgin, Hausa, Yoruba, Igbo. I am like ChatGPT but designed for Nigerian life. What would you like to explore?";
      if(/air|oxygen|gas|atmosphere/.test(tl)) return "Air is a mixture of gases: 78% Nitrogen, 21% Oxygen, 1% Argon, 0.04% CO2. Oxygen (O2) is just one component of air. Air = mixture; Oxygen = one pure gas. We breathe air, not pure oxygen. Pure oxygen is used in hospitals and welding.";
      if(/water|h2o|liquid/.test(tl)) return "Water (H2O) is essential for all life. Properties: Boils at 100°C, freezes at 0°C, universal solvent, covers 71% of Earth. Human body is 60% water — drink 8 glasses/day minimum. In Nigeria: Always use treated/clean water to avoid cholera and typhoid.";
      if(/money|naira|finance|budget|saving/.test(tl)) return "Smart money management: Use the 50-30-20 rule — 50% on needs (food, rent, transport), 30% on wants, 20% on savings. Average Nigerian earns N6,277/month, saves N617 (9.8%). To save more: track every expense, reduce airtime, cook at home. Use Piggyvest or Kuda for automated savings!";
      // Generic but helpful for any topic
      return "Here is what I know about "+topicWords+": This is an interesting topic that covers important concepts. For a complete detailed answer, type your full question and I will explain everything step by step with examples. I cover science, technology, health, education, Nigerian culture, finance, history, and much more — just ask directly!";
    }
  }

  // --- YES/NO ---
  if(/^(yes|yeah|yep|sure|okay|ok|alright|fine|go ahead|proceed|please|continue)$/.test(m))
    return "Great! Go ahead and share your question or topic. I am ready to help!";
  if(/^(no|nope|not really|never mind|forget it|nothing)$/.test(m))
    return "No problem at all! Whenever you are ready to ask anything, I am here. Just type your question anytime.";

  // --- SHORT INPUT ---
  if(m.length<3) return "Hello! Ask me anything. I am ready to help with any topic!";

  // --- CATCHALL: Always give a helpful, direct response ---
  if(/do you know me|know me|who am i/.test(m)) return "You are my valued user! I do not store personal data between sessions, but in this conversation I remember everything you share. Tell me your name and I will use it. What would you like to discuss?";
  if(/\btanadi\b/.test(m)) return "I am Tanadi — your AI assistant for savings intelligence and general knowledge, built for Nigerian users. Ask me anything!";
  var words=m.replace(/[^a-z\s]/g,'').trim().split(/\s+/).filter(function(w){return w.length>2;});
  var mainWord=words.length>0?words[words.length-1]:m.slice(0,15);
  return "I am Tanadi, your AI assistant! I am ready to help with any topic — science, technology, health, finance, Nigerian banking, history, grammar, mathematics, relationships, culture, and much more. For a full detailed answer, ask directly — for example: 'What is "+mainWord+"?' and I will explain everything clearly with examples!";
}
"""

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"/>
<title>Tanadi</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=Nunito:wght@400;600;700;800;900&display=swap');
:root{
  --bg:#07101f;--surf:#0f1c2e;--card:#132540;--border:#1c3454;
  --accent:#00d4aa;--gold:#f4a916;--red:#f05252;--blue:#4a9eff;
  --purple:#a855f7;--green:#10b981;--text:#e0eefa;--muted:#4d7299;
}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent;}
body{background:var(--bg);color:var(--text);font-family:'Nunito',sans-serif;display:flex;flex-direction:column;height:100vh;overflow:hidden;}
header{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--surf);border-bottom:1px solid var(--border);flex-shrink:0;}
.logo{display:flex;align-items:center;gap:10px;}
.logo-icon{width:38px;height:38px;border-radius:50%;background:linear-gradient(135deg,var(--accent),#0080ff);display:flex;align-items:center;justify-content:center;font-size:19px;font-weight:900;color:#fff;}
.logo-name{font-family:'Playfair Display',serif;font-size:20px;color:#fff;line-height:1;}
.logo-sub{font-size:9px;color:var(--accent);letter-spacing:2px;text-transform:uppercase;}
.score-pill{display:flex;align-items:center;gap:8px;background:var(--card);border:1px solid var(--border);border-radius:22px;padding:5px 14px;}
.score-num{font-size:22px;font-weight:900;line-height:1;}
.slbl{font-size:8px;color:var(--muted);text-transform:uppercase;}
.stag{font-size:11px;font-weight:800;}
.stats{display:flex;overflow-x:auto;background:var(--card);border-bottom:1px solid var(--border);scrollbar-width:none;flex-shrink:0;}
.stats::-webkit-scrollbar{display:none;}
.stat{padding:6px 13px;text-align:center;border-right:1px solid var(--border);white-space:nowrap;flex-shrink:0;}
.sv{font-size:12px;color:var(--accent);font-weight:700;}
.sl{font-size:8px;color:var(--muted);}
.tabs{display:flex;background:var(--surf);border-bottom:2px solid var(--border);flex-shrink:0;}
.tab{flex:1;padding:7px 2px;text-align:center;font-size:9px;font-weight:800;cursor:pointer;color:var(--muted);border-bottom:3px solid transparent;transition:all .2s;}
.tab.active{color:var(--accent);border-bottom-color:var(--accent);}
.tab-icon{font-size:13px;display:block;margin-bottom:1px;}
.page{display:none;flex:1;flex-direction:column;overflow:hidden;min-height:0;}
.page.active{display:flex;}
.sc{flex:1;overflow-y:auto;padding:14px;}
.card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:14px;margin-bottom:12px;}
.sec{font-size:10px;color:var(--accent);font-weight:800;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:11px;}
.bar{height:7px;background:var(--border);border-radius:4px;overflow:hidden;}
.barf{height:100%;border-radius:4px;transition:width .5s ease;}
.fld{margin-bottom:10px;}
.fld label{font-size:10px;color:var(--muted);display:block;margin-bottom:3px;text-transform:uppercase;letter-spacing:.5px;font-weight:700;}
.fld input,.fld select{width:100%;background:var(--surf);border:1.5px solid var(--border);border-radius:9px;padding:10px 12px;color:var(--text);font-size:14px;font-family:'Nunito',sans-serif;font-weight:700;outline:none;}
.fld input:focus,.fld select:focus{border-color:var(--accent);}
.fld select option{background:var(--surf);}
.btn{width:100%;padding:13px;border:none;border-radius:11px;font-size:14px;font-family:'Nunito',sans-serif;font-weight:800;cursor:pointer;margin-top:6px;letter-spacing:.3px;}
.btn:disabled{opacity:.35;cursor:default;}
.bg{background:linear-gradient(135deg,var(--accent),#00b894);color:#fff;box-shadow:0 4px 14px rgba(0,212,170,.3);}
.bb{background:linear-gradient(135deg,var(--blue),#0055dd);color:#fff;}
.bgold{background:linear-gradient(135deg,var(--gold),#d97706);color:#fff;}
.bo{background:transparent;border:1.5px solid var(--border)!important;color:var(--text);}
.er{display:flex;align-items:center;gap:10px;margin-bottom:10px;}
.eico{width:38px;height:38px;border-radius:10px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:18px;}
.elb{flex:1;font-size:13px;font-weight:700;}
.esb{font-size:10px;color:var(--muted);font-weight:400;}
.epx{font-size:13px;color:var(--muted);flex-shrink:0;font-weight:800;}
.ein{width:105px;background:var(--surf);border:1.5px solid var(--border);border-radius:9px;padding:9px 10px;color:var(--text);font-size:15px;font-family:'Nunito',sans-serif;font-weight:800;outline:none;text-align:right;}
.ein:focus{border-color:var(--accent);}
.rsr{display:flex;align-items:center;gap:14px;margin-bottom:14px;padding-bottom:14px;border-bottom:1px solid var(--border);}
.bsc{width:66px;height:66px;border-radius:50%;flex-shrink:0;display:flex;flex-direction:column;align-items:center;justify-content:center;}
.bsn{font-size:25px;font-weight:900;color:#fff;line-height:1;}
.bsl{font-size:8px;font-weight:800;color:rgba(255,255,255,.7);text-transform:uppercase;}
.rgrid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px;}
.rgi{background:var(--surf);border:1px solid var(--border);border-radius:10px;padding:10px 12px;}
.rgiv{font-size:17px;font-weight:900;margin-bottom:2px;}
.rgil{font-size:8px;color:var(--muted);text-transform:uppercase;}
.spr{display:flex;align-items:center;gap:8px;margin-bottom:7px;}
.sn{width:82px;font-size:12px;font-weight:700;flex-shrink:0;}
.sbw{flex:1;}
.sb{height:5px;background:var(--border);border-radius:3px;overflow:hidden;}
.sbf{height:100%;border-radius:3px;}
.sp{width:34px;text-align:right;font-size:11px;font-weight:800;flex-shrink:0;}
.abx{background:rgba(0,212,170,.07);border-left:3px solid var(--accent);border-radius:0 10px 10px 0;padding:12px;margin-bottom:10px;font-size:13px;line-height:1.65;}
.abl{font-size:9px;color:var(--accent);font-weight:800;letter-spacing:1px;text-transform:uppercase;margin-bottom:5px;}
.aibx{background:rgba(74,158,255,.08);border:1px solid rgba(74,158,255,.25);border-radius:10px;padding:12px;margin-bottom:10px;font-size:13px;line-height:1.7;display:none;}
.ail{font-size:9px;color:var(--blue);font-weight:800;letter-spacing:1px;text-transform:uppercase;margin-bottom:5px;}
/* CHAT */
#chatMsgs{flex:1;overflow-y:auto;padding:12px 12px 4px;}
.msg{display:flex;margin-bottom:10px;animation:fadeUp .2s ease;}
.msg.user{justify-content:flex-end;}
.av{width:30px;height:30px;border-radius:50%;flex-shrink:0;margin-top:2px;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:900;}
.msg.bot .av{background:linear-gradient(135deg,var(--accent),#0080ff);color:#fff;margin-right:8px;}
.msg.user .av{background:var(--border);color:var(--muted);margin-left:8px;}
.bub{max-width:84%;padding:10px 13px;font-size:13.5px;line-height:1.7;}
.msg.bot .bub{background:var(--card);border:1px solid var(--border);border-radius:3px 14px 14px 14px;}
.msg.user .bub{background:rgba(0,212,170,.1);border:1px solid rgba(0,212,170,.3);border-radius:14px 3px 14px 14px;}
.bub b{color:var(--accent);}
.nr{color:var(--gold);font-weight:800;}
.typing-dots{display:flex;align-items:center;gap:5px;padding:4px 0;}
.dot{width:7px;height:7px;border-radius:50%;background:var(--accent);animation:pulse 1.1s infinite;}
.dot:nth-child(2){animation-delay:.2s;}.dot:nth-child(3){animation-delay:.4s;}
.chat-foot{padding:8px 12px 14px;border-top:1px solid var(--border);background:var(--surf);flex-shrink:0;}
.hints{display:flex;gap:7px;overflow-x:auto;padding-bottom:8px;scrollbar-width:none;}
.hints::-webkit-scrollbar{display:none;}
.hint{flex-shrink:0;background:var(--card);border:1px solid var(--border);border-radius:20px;padding:6px 13px;font-size:11.5px;color:var(--muted);cursor:pointer;white-space:nowrap;font-family:'Nunito',sans-serif;transition:all .15s;}
.hint:active{border-color:var(--accent);color:var(--accent);}
.irow{display:flex;gap:8px;align-items:flex-end;background:var(--card);border:1.5px solid var(--border);border-radius:13px;padding:8px 8px 8px 14px;margin-top:6px;}
#chatTxt{flex:1;background:transparent;border:none;outline:none;color:var(--text);font-size:14px;font-family:'Nunito',sans-serif;resize:none;line-height:1.5;max-height:80px;}
#chatTxt::placeholder{color:var(--muted);}
.send-btn{width:36px;height:36px;border-radius:9px;border:none;background:linear-gradient(135deg,var(--accent),#0080ff);color:#fff;font-size:18px;cursor:pointer;flex-shrink:0;}
.send-btn:disabled{opacity:.3;}
.cstat{font-size:10px;padding:3px 1px;min-height:16px;}
/* BANK */
.bhero{background:linear-gradient(135deg,rgba(74,158,255,.15),rgba(168,85,247,.1));border:1px solid rgba(74,158,255,.3);border-radius:16px;padding:18px;text-align:center;margin-bottom:14px;}
.ban{font-family:'Playfair Display',serif;font-size:28px;color:#fff;margin:4px 0;letter-spacing:2px;}
.bahn{font-size:15px;color:var(--text);font-weight:800;}
.vbadge{display:inline-block;background:rgba(0,212,170,.15);border:1px solid var(--accent);border-radius:20px;padding:3px 14px;font-size:11px;color:var(--accent);font-weight:800;margin-top:6px;}
.balhero{background:linear-gradient(135deg,rgba(16,185,129,.15),rgba(0,212,170,.1));border:1px solid rgba(16,185,129,.3);border-radius:12px;padding:14px;display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;}
.pbl{font-size:10px;color:var(--green);font-weight:800;letter-spacing:1px;text-transform:uppercase;}
.pbn{font-size:22px;font-weight:900;color:#fff;margin-top:2px;}
.rbox{border-radius:10px;padding:12px;margin:10px 0;font-size:13px;line-height:1.65;}
.rok{background:rgba(0,212,170,.1);border:1px solid rgba(0,212,170,.3);color:var(--accent);}
.rerr{background:rgba(240,82,82,.1);border:1px solid rgba(240,82,82,.3);color:var(--red);}
.rinfo{background:rgba(74,158,255,.1);border:1px solid rgba(74,158,255,.3);color:var(--blue);}
.nbox{background:rgba(244,169,22,.08);border:1px solid rgba(244,169,22,.25);border-radius:10px;padding:12px;font-size:12px;color:#fbbf24;line-height:1.65;margin-top:10px;}
.ugrid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px;}
.ui{background:var(--surf);border:1px solid var(--border);border-radius:9px;padding:10px;text-align:center;}
.uc{font-size:16px;font-weight:900;color:var(--accent);}
.ub{font-size:10px;color:var(--muted);margin-top:2px;}
.sok{color:var(--accent);font-weight:700;}
.serr{color:var(--red);font-weight:700;}
/* VAULT */
.vhero{background:linear-gradient(135deg,rgba(0,212,170,.12),rgba(0,128,255,.1));border:1px solid rgba(0,212,170,.25);border-radius:16px;padding:18px;text-align:center;margin-bottom:14px;}
.vbl{font-size:9px;color:var(--accent);letter-spacing:2px;text-transform:uppercase;font-weight:800;}
.vba{font-family:'Playfair Display',serif;font-size:40px;color:#fff;margin:5px 0;line-height:1;}
.vsb{font-size:11px;color:var(--muted);}
.vact{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-bottom:14px;}
.vd{padding:13px;background:linear-gradient(135deg,var(--accent),#00b894);border:none;border-radius:10px;color:#fff;font-size:14px;font-family:'Nunito',sans-serif;font-weight:800;cursor:pointer;}
.vw{padding:13px;background:var(--card);border:1.5px solid var(--border);border-radius:10px;color:var(--text);font-size:14px;font-family:'Nunito',sans-serif;font-weight:700;cursor:pointer;}
.txb{background:var(--card);border:1px solid var(--border);border-radius:12px;overflow:hidden;}
.txh{padding:10px 13px;font-size:9px;color:var(--accent);letter-spacing:1px;text-transform:uppercase;font-weight:800;border-bottom:1px solid var(--border);}
.txr{display:flex;align-items:center;justify-content:space-between;padding:10px 13px;border-bottom:1px solid var(--border);}
.txr:last-child{border-bottom:none;}
.txi{width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:900;margin-right:9px;flex-shrink:0;}
.dep .txi{background:rgba(0,212,170,.15);color:var(--accent);}
.wit .txi{background:rgba(240,82,82,.15);color:var(--red);}
.rcv .txi{background:rgba(16,185,129,.15);color:var(--green);}
.txl{display:flex;align-items:center;}
.txn{font-size:12px;font-weight:700;}
.txd{font-size:9px;color:var(--muted);}
.dep .txa,.rcv .txa{color:var(--accent);font-weight:800;font-size:13px;}
.wit .txa{color:var(--red);font-weight:800;font-size:13px;}
.empty{padding:24px;text-align:center;color:var(--muted);font-size:13px;}
/* GAME */
.game-wrap{flex:1;display:flex;flex-direction:column;overflow:hidden;background:#0a1628;}
.game-hud{display:flex;justify-content:space-around;padding:7px 10px;background:#0f1c2e;border-bottom:1px solid var(--border);flex-shrink:0;}
.hud-item{text-align:center;}
.hud-val{font-size:18px;font-weight:900;}
.hud-lbl{font-size:8px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;}
#gameCanvas{display:block;width:100%;flex:1;}
.game-btns{display:flex;gap:8px;padding:8px 12px 10px;background:#0f1c2e;border-top:1px solid var(--border);flex-shrink:0;}
.gbtn{flex:1;padding:14px 8px;border:none;border-radius:10px;font-family:'Nunito',sans-serif;font-size:15px;font-weight:900;cursor:pointer;user-select:none;-webkit-user-select:none;}
.gb-l{background:rgba(74,158,255,.2);color:var(--blue);border:2px solid rgba(74,158,255,.4);}
.gb-j{background:linear-gradient(135deg,var(--accent),#00b894);color:#fff;font-size:20px;}
.gb-r{background:rgba(168,85,247,.2);color:var(--purple);border:2px solid rgba(168,85,247,.4);}
/* MODALS */
.mbg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.9);z-index:200;align-items:flex-end;justify-content:center;}
.mbg.open{display:flex;}
.mbox{background:var(--surf);border:1px solid var(--border);border-radius:18px 18px 0 0;padding:22px;width:100%;max-width:480px;}
.mbox h3{font-size:16px;margin-bottom:14px;color:var(--accent);font-weight:800;}
.mbox input{width:100%;background:var(--card);border:1.5px solid var(--border);border-radius:9px;padding:12px 13px;color:var(--text);font-size:16px;font-family:'Nunito',sans-serif;font-weight:700;outline:none;margin-bottom:10px;}
.mbox input:focus{border-color:var(--accent);}
.mbtns{display:flex;gap:8px;margin-top:4px;}
.mbtns button{flex:1;padding:12px;border-radius:9px;font-family:'Nunito',sans-serif;font-size:14px;font-weight:800;cursor:pointer;border:none;}
.mok{background:linear-gradient(135deg,var(--accent),#0080ff);color:#fff;}
.mcan{background:var(--border);color:var(--muted);}
.wbg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.93);z-index:210;overflow-y:auto;}
.wbg.open{display:block;}
.wbox{background:var(--surf);border-radius:18px;padding:20px;margin:16px;}
.step-r{display:flex;gap:12px;align-items:flex-start;margin-bottom:9px;background:var(--card);border-radius:10px;padding:12px;}
.step-n{width:26px;height:26px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:900;color:#fff;}
.step-t{font-size:12px;line-height:1.65;color:var(--text);}
.step-t b{color:var(--accent);}
@keyframes fadeUp{from{opacity:0;transform:translateY(7px);}to{opacity:1;transform:translateY(0);}}
@keyframes pulse{0%,100%{opacity:.3;transform:scale(.8);}50%{opacity:1;transform:scale(1.2);}}
::-webkit-scrollbar{width:3px;}::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px;}
</style>
</head>
<body>
<header>
  <div class="logo">
    <div class="logo-icon">N</div>
    <div><div class="logo-name">Tanadi</div><div class="logo-sub">Savings Intelligence</div></div>
  </div>
  <div class="score-pill">
    <div class="score-num" id="hScore" style="color:var(--muted)">--</div>
    <div><div class="slbl">Score</div><div class="stag" id="hTag" style="color:var(--muted)">N/A</div></div>
  </div>
</header>
<div class="stats">
  <div class="stat"><div class="sv">N6,277</div><div class="sl">Avg Income</div></div>
  <div class="stat"><div class="sv">N617</div><div class="sl">Avg Savings</div></div>
  <div class="stat"><div class="sv">9.8%</div><div class="sl">Save Rate</div></div>
  <div class="stat"><div class="sv">20.4%</div><div class="sl">Zero Savers</div></div>
  <div class="stat"><div class="sv">10,000</div><div class="sl">Records</div></div>
</div>
<div class="tabs">
  <div class="tab active" id="t0" onclick="goTab('pg-budget',0)"><span class="tab-icon">&#x1F4CA;</span>Budget</div>
  <div class="tab" id="t1" onclick="goTab('pg-chat',1)"><span class="tab-icon">&#x1F4AC;</span>Chat</div>
  <div class="tab" id="t2" onclick="goTab('pg-bank',2)"><span class="tab-icon">&#x1F3E6;</span>Bank</div>
  <div class="tab" id="t3" onclick="goTab('pg-vault',3)"><span class="tab-icon">&#x1F4B3;</span>Vault</div>
  <div class="tab" id="t4" onclick="goTab('pg-game',4)"><span class="tab-icon">&#x1F3AE;</span>Game</div>
</div>

<!-- BUDGET -->
<div id="pg-budget" class="page active" style="flex-direction:column;">
<div class="sc">
  <div style="background:linear-gradient(135deg,rgba(0,212,170,.12),rgba(0,128,255,.1));border:1px solid rgba(0,212,170,.25);border-radius:14px;padding:14px;margin-bottom:14px;text-align:center;">
    <div style="font-size:15px;font-weight:900;color:#fff;margin-bottom:4px;">Monthly Budget Tracker</div>
    <div style="font-size:12px;color:var(--muted);line-height:1.5;">Enter income and expenses for instant AI savings advice</div>
  </div>
  <div class="card">
    <div class="sec">Income This Month</div>
    <div class="er"><div class="eico" style="background:rgba(0,212,170,.15);">&#x1F4B4;</div>
      <div class="elb">Monthly Income<div class="esb">Salary, business, any source</div></div>
      <div class="epx">N</div><input class="ein" type="number" id="b_inc" placeholder="0" oninput="liveUp()"/></div>
  </div>
  <div class="card">
    <div class="sec">Expenses This Month</div>
    <div class="er"><div class="eico" style="background:rgba(244,169,22,.15);">&#x1F372;</div>
      <div class="elb">Food &amp; Groceries<div class="esb">Meals, market, restaurant</div></div>
      <div class="epx">N</div><input class="ein" type="number" id="b_food" placeholder="0" oninput="liveUp()"/></div>
    <div class="er"><div class="eico" style="background:rgba(74,158,255,.15);">&#x1F68C;</div>
      <div class="elb">Transport<div class="esb">Bus, keke, okada, fuel</div></div>
      <div class="epx">N</div><input class="ein" type="number" id="b_tra" placeholder="0" oninput="liveUp()"/></div>
    <div class="er"><div class="eico" style="background:rgba(168,85,247,.15);">&#x1F4F1;</div>
      <div class="elb">Airtime &amp; Data<div class="esb">Mobile recharge, internet</div></div>
      <div class="epx">N</div><input class="ein" type="number" id="b_air" placeholder="0" oninput="liveUp()"/></div>
    <div class="er"><div class="eico" style="background:rgba(240,82,82,.15);">&#x1F4CB;</div>
      <div class="elb">Other Expenses<div class="esb">Rent, bills, clothing, misc</div></div>
      <div class="epx">N</div><input class="ein" type="number" id="b_oth" placeholder="0" oninput="liveUp()"/></div>
  </div>
  <div id="liveSummary" style="display:none;" class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
      <span class="sec" style="margin:0;">Live Summary</span>
      <span id="liveScore" style="font-size:13px;font-weight:900;"></span>
    </div>
    <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:5px;">
      <span style="color:var(--muted);">Total Spent</span><span id="liveSpent" style="font-weight:800;color:var(--red);">N0</span>
    </div>
    <div style="display:flex;justify-content:space-between;font-size:16px;margin-bottom:8px;">
      <span style="color:var(--muted);">Can Save</span><span id="liveSave" style="font-weight:900;">N0</span>
    </div>
    <div class="bar"><div class="barf" id="liveBar" style="width:0%;"></div></div>
  </div>
  <button class="btn bg" id="analyseBtn" onclick="doAnalyse()" disabled>&#x26A1; Analyse with AI</button>
  <div class="card" id="resultPanel" style="display:none;margin-top:12px;">
    <div class="rsr">
      <div class="bsc" id="scoreCircle"><div class="bsn" id="rScoreNum">0</div><div class="bsl">Score</div></div>
      <div><div style="font-size:17px;font-weight:900;color:#fff;" id="rGrade">--</div>
           <div style="font-size:12px;color:var(--muted);margin-top:3px;line-height:1.5;" id="rDesc">--</div></div>
    </div>
    <div class="rgrid">
      <div class="rgi"><div class="rgiv" id="rActual">N0</div><div class="rgil">You Can Save</div></div>
      <div class="rgi"><div class="rgiv" id="rTarget" style="color:var(--gold);">N0</div><div class="rgil">ML Target</div></div>
      <div class="rgi"><div class="rgiv" id="rRate" style="color:var(--blue);">0%</div><div class="rgil">Savings Rate</div></div>
      <div class="rgi"><div class="rgiv" id="rPeer" style="color:var(--muted);">N0</div><div class="rgil">Peers Save</div></div>
    </div>
    <div style="margin:4px 0 14px;">
      <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--muted);margin-bottom:4px;"><span>Score</span><span id="rBarLbl" style="font-weight:800;"></span></div>
      <div class="bar"><div class="barf" id="rScoreBar" style="width:0%;"></div></div>
    </div>
    <div class="sec">Where Your Money Goes</div>
    <div id="spendBars" style="margin-bottom:12px;"></div>
    <div class="abx"><div class="abl">Biggest Opportunity</div><div id="rAdvice">--</div></div>
    <div class="aibx" id="aiBox"><div class="ail">Tanadi AI Advice</div><div id="aiText"></div></div>
    <button class="btn bg" onclick="saveRec()">Save to Vault</button>
    <button class="btn bb" style="margin-top:8px;" onclick="sendBudgetToBank()">Send to Bank Account</button>
  </div>
</div>
</div>

<!-- CHAT -->
<div id="pg-chat" class="page" style="flex-direction:column;">
  <div id="chatMsgs"></div>
  <div class="chat-foot">
    <div class="hints" id="chatHints">
      <div class="hint" onclick="hs(this)">Hi Tanadi!</div>
      <div class="hint" onclick="hs(this)">I earn N7,000, spent N5,200 this month</div>
      <div class="hint" onclick="hs(this)">How much should I save?</div>
      <div class="hint" onclick="hs(this)">Tips to save on food</div>
      <div class="hint" onclick="hs(this)">I spend all my money always</div>
      <div class="hint" onclick="hs(this)">Best savings strategy for low income</div>
    </div>
    <div class="irow">
      <textarea id="chatTxt" rows="1" placeholder="Ask me anything about saving money..."></textarea>
      <button class="send-btn" id="chatBtn" onclick="chatSend()">&#x2192;</button>
      <button class="clear-btn" onclick="clearChat()" title="Clear chat history">🗑️</button>
    </div>
    <div class="cstat" id="cstat"></div>
  </div>
</div>

<!-- BANK -->
<div id="pg-bank" class="page" style="flex-direction:column;">
<div class="sc">
  <div id="bankLinked" style="display:none;">
    <div class="bhero">
      <div style="font-size:11px;color:var(--blue);letter-spacing:2px;text-transform:uppercase;font-weight:800;" id="bkBank">Bank</div>
      <div class="ban" id="bkNum">0000000000</div>
      <div class="bahn" id="bkName">Account Name</div>
      <div class="vbadge">&#x2705; Verified Account</div>
    </div>
    <div class="balhero">
      <div><div class="pbl">Paystack Balance</div><div class="pbn" id="psBal">--</div></div>
      <button onclick="loadBal()" style="background:rgba(16,185,129,.2);border:1px solid rgba(16,185,129,.4);border-radius:8px;padding:8px 12px;color:var(--green);font-family:'Nunito',sans-serif;font-size:12px;font-weight:800;cursor:pointer;">Refresh</button>
    </div>
    <div class="card">
      <div class="sec">Send Savings to Bank Account</div>
      <p style="font-size:12px;color:var(--muted);margin-bottom:11px;line-height:1.6;">Transfer from your Paystack balance directly to your linked bank account.</p>
      <div class="fld"><label>Amount (N)</label><input type="number" id="sendAmt" placeholder="e.g. 500"/></div>
      <div class="fld"><label>Note</label><input type="text" id="sendNote" placeholder="Monthly savings"/></div>
      <div id="sendRes" style="display:none;" class="rbox"></div>
      <button class="btn bb" onclick="doSend()">Send to Bank Account</button>
      <div class="nbox">Requires funded Paystack balance. Fund at dashboard.paystack.com</div>
    </div>
    <div class="card">
      <div class="sec">Receive Money via Payment Link</div>
      <p style="font-size:12px;color:var(--muted);margin-bottom:11px;line-height:1.6;">Generate a Paystack link. Pay with any card, bank transfer, or USSD. Money goes into your vault.</p>
      <div class="fld"><label>Amount (N)</label><input type="number" id="recvAmt" placeholder="e.g. 1000"/></div>
      <div class="fld"><label>Your Email</label><input type="email" id="recvEmail" placeholder="your@email.com"/></div>
      <div id="recvRes" style="display:none;" class="rbox"></div>
      <button class="btn bgold" onclick="doReceive()">Generate Payment Link</button>
      <button class="btn bo" style="margin-top:8px;" onclick="doVerifyPay()">I Have Paid - Verify &amp; Add to Vault</button>
    </div>
    <div class="card">
      <div class="sec">USSD Quick Codes</div>
      <p style="font-size:12px;color:var(--muted);margin-bottom:9px;">Dial directly - no internet needed.</p>
      <div class="ugrid">
        <div class="ui"><div class="uc">*737#</div><div class="ub">GTBank</div></div>
        <div class="ui"><div class="uc">*901#</div><div class="ub">Access Bank</div></div>
        <div class="ui"><div class="uc">*955#</div><div class="ub">OPay</div></div>
        <div class="ui"><div class="uc">*945#</div><div class="ub">PalmPay</div></div>
        <div class="ui"><div class="uc">*894#</div><div class="ub">First Bank</div></div>
        <div class="ui"><div class="uc">*919#</div><div class="ub">UBA</div></div>
        <div class="ui"><div class="uc">*966#</div><div class="ub">Zenith</div></div>
        <div class="ui"><div class="uc">*833#</div><div class="ub">Kuda</div></div>
      </div>
    </div>
    <button class="btn bo" onclick="unlinkBank()">Unlink Account</button>
  </div>
  <div id="bankUnlinked">
    <div style="background:linear-gradient(135deg,rgba(74,158,255,.15),rgba(168,85,247,.1));border:1px solid rgba(74,158,255,.3);border-radius:14px;padding:16px;text-align:center;margin-bottom:14px;">
      <div style="font-size:34px;margin-bottom:8px;">&#x1F3E6;</div>
      <div style="font-size:15px;font-weight:900;color:#fff;margin-bottom:4px;">Link Your Bank Account</div>
      <div style="font-size:12px;color:var(--muted);line-height:1.5;">40+ Nigerian banks - GTBank, Access, OPay, PalmPay, Kuda &amp; more</div>
    </div>
    <div id="testLimitBox" class="nbox" style="display:none;margin-bottom:12px;">
      <b>Daily verification limit reached (Paystack test mode allows 3/day).</b><br/>
      Options:<br/>
      1. Try again tomorrow<br/>
      2. Use Live mode keys from dashboard.paystack.com<br/>
      3. Enter account manually below and tap "Link Without Verify"
    </div>
    <div id="keyWarn" class="nbox" style="display:none;margin-bottom:12px;">
      <b>Paystack key not set.</b> Open tanadi_config.py and paste your sk_test_ key.<br/>
      <b>You can still link your account manually</b> using the button below.
    </div>
    <div class="card">
      <div class="sec">Account Details</div>
      <div class="fld"><label>Select Your Bank</label>
        <select id="bankSel" onchange="onBankChange()">
          <option value="">-- Loading banks... --</option>
        </select></div>
      <div class="fld"><label>Account Number (10 digits)</label>
        <input type="number" id="acctNo" placeholder="0000000000" oninput="onAcctIn()"/></div>
      <div id="vstatus" style="font-size:13px;padding:5px 0;min-height:24px;font-weight:700;"></div>
      <div id="vname" style="display:none;background:rgba(0,212,170,.1);border:1px solid rgba(0,212,170,.3);border-radius:9px;padding:10px 12px;font-size:15px;font-weight:900;color:var(--accent);margin-bottom:10px;text-align:center;"></div>
      <div id="manualNameBox" class="fld">
        <label>Your Full Account Name</label>
        <input type="text" id="manualName" placeholder="e.g. JOHN DOE SMITH"/>
        <div style="font-size:10px;color:var(--muted);margin-top:3px;">Enter exactly as on your bank card/statement</div>
      </div>
      <div id="vstatus2" style="font-size:12px;padding:4px 0;min-height:18px;"></div>
      <button class="btn bb" id="linkBtn" onclick="linkAcct()" disabled>Link This Account (Auto-Verified)</button>
      <div style="display:flex;align-items:center;gap:8px;margin:10px 0;">
        <div style="flex:1;height:1px;background:var(--border);"></div>
        <span style="font-size:10px;color:var(--muted);font-weight:700;">OR</span>
        <div style="flex:1;height:1px;background:var(--border);"></div>
      </div>
      <button class="btn bg" id="manualLinkBtn" onclick="linkManual()" style="background:linear-gradient(135deg,#f4a916,#d97706);">Link Account Manually (No Verification Needed)</button>
    </div>
    <div class="nbox">Your account is verified securely via Paystack. Your PIN is never accessed by this app.</div>
  </div>
</div>
</div>

<!-- VAULT -->
<div id="pg-vault" class="page" style="flex-direction:column;">
<div class="sc">
  <div class="vhero">
    <div class="vbl">Vault Balance</div>
    <div class="vba">N<span id="vBal">0</span></div>
    <div class="vsb" id="vSub">Start saving today</div>
    <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--muted);margin:10px 0 4px;">
      <span>Progress to N5,000 Goal</span><span id="vPct">0%</span>
    </div>
    <div class="bar"><div class="barf" id="vBar" style="width:0%;background:var(--accent);"></div></div>
  </div>
  <div class="vact">
    <button class="vd" onclick="openModal('deposit')">+ Deposit</button>
    <button class="vw" onclick="showWd()">- Withdraw</button>
  </div>
  <div class="card">
    <div class="sec">Pay with Card / Bank Transfer / USSD</div>
    <p style="font-size:12px;color:var(--muted);margin-bottom:11px;line-height:1.6;">Add real money using your bank card, transfer, or USSD code. Works with all Nigerian banks.</p>
    <div class="fld"><label>Amount to Add (N)</label><input type="number" id="vDepAmt" placeholder="e.g. 1000" oninput="checkVDep()"/></div>
    <div class="fld"><label>Your Email (for payment receipt)</label><input type="email" id="vDepEmail" placeholder="your@email.com" oninput="checkVDep()"/></div>
    <div id="vDepRes" style="display:none;" class="rbox"></div>
    <button class="btn bg" id="vDepBtn" onclick="vaultPay()" disabled>Generate Payment Link</button>
    <button class="btn bo" id="vVerBtn" style="margin-top:8px;display:none;" onclick="vaultVerify()">I Have Paid - Add to Vault</button>
  </div>
  <div class="txb">
    <div class="txh">Transaction History</div>
    <div id="txList"><div class="empty">No transactions yet.<br/>Make your first deposit!</div></div>
  </div>
  <div style="background:rgba(74,158,255,.08);border:1px solid rgba(74,158,255,.2);border-radius:10px;padding:12px;font-size:12px;color:#80b8ff;margin-top:12px;line-height:1.7;">
    <b>USSD to add money:</b> GTBank *737# | Access *901# | OPay *955# | First Bank *894#
  </div>
</div>
</div>

<!-- GAME: NAIRA RUNNER (real canvas platformer) -->
<div id="pg-game" class="page" style="flex-direction:column;">
  <div class="game-hud">
    <div class="hud-item"><div class="hud-val" id="gScore" style="color:var(--gold);">0</div><div class="hud-lbl">Score</div></div>
    <div class="hud-item"><div class="hud-val" id="gCoins" style="color:var(--accent);">0</div><div class="hud-lbl">Coins</div></div>
    <div class="hud-item"><div class="hud-val" id="gLives" style="color:var(--red);">3</div><div class="hud-lbl">Lives</div></div>
    <div class="hud-item"><div class="hud-val" id="gBest" style="color:var(--purple);">0</div><div class="hud-lbl">Best</div></div>
    <div class="hud-item"><div class="hud-val" id="gLevel" style="color:var(--blue);">1</div><div class="hud-lbl">Level</div></div>
  </div>
  <div class="game-wrap">
    <canvas id="gameCanvas"></canvas>
  </div>
  <div class="game-btns">
    <button class="gbtn gb-l" id="btnL" ontouchstart="kL=true;return false;" ontouchend="kL=false;return false;" onmousedown="kL=true" onmouseup="kL=false">&#x25C4;</button>
    <button class="gbtn gb-j" ontouchstart="doJump();return false;" onmousedown="doJump()">&#x2B06;</button>
    <button class="gbtn gb-r" id="btnR" ontouchstart="kR=true;return false;" ontouchend="kR=false;return false;" onmousedown="kR=true" onmouseup="kR=false">&#x25BA;</button>
  </div>
</div>

<!-- DEPOSIT/WITHDRAW MODAL -->
<div class="mbg" id="modal">
  <div class="mbox">
    <h3 id="mTitle">Deposit to Vault</h3>
    <input type="number" id="mAmt" placeholder="Amount (N)"/>
    <input type="text" id="mNote" placeholder="Note (optional)"/>
    <div class="mbtns">
      <button class="mcan" onclick="closeModal()">Cancel</button>
      <button class="mok" onclick="doModal()">Confirm</button>
    </div>
  </div>
</div>

<!-- WITHDRAW GUIDE -->
<div class="wbg" id="wdGuide">
  <div class="wbox">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
      <div style="font-size:16px;font-weight:900;color:var(--accent);">How to Withdraw</div>
      <button onclick="hideWd()" style="background:var(--border);border:none;border-radius:8px;padding:7px 14px;color:var(--text);font-family:'Nunito',sans-serif;font-weight:800;cursor:pointer;">Close</button>
    </div>
    <p style="font-size:12px;color:var(--muted);margin-bottom:14px;line-height:1.6;">Your Tanadi Vault tracks savings. Use any method below to get real cash:</p>
    <div style="font-size:10px;color:var(--accent);font-weight:800;letter-spacing:1px;text-transform:uppercase;margin-bottom:8px;">Option 1 - Paystack Transfer</div>
    <div class="step-r"><div class="step-n" style="background:var(--accent);">1</div><div class="step-t">Go to <b>Bank tab</b> and link your account.</div></div>
    <div class="step-r"><div class="step-n" style="background:var(--accent);">2</div><div class="step-t">Tap <b>Send Savings to Bank</b> - money arrives in minutes.</div></div>
    <div class="nbox" style="margin:6px 0 12px;">Requires funded Paystack balance at dashboard.paystack.com</div>
    <div style="font-size:10px;color:var(--gold);font-weight:800;letter-spacing:1px;text-transform:uppercase;margin-bottom:8px;">Option 2 - USSD Direct</div>
    <div class="step-r"><div class="step-n" style="background:var(--gold);">1</div><div class="step-t">Dial your bank code: GTBank <b>*737#</b>, Access <b>*901#</b>, First Bank <b>*894#</b></div></div>
    <div class="step-r"><div class="step-n" style="background:var(--gold);">2</div><div class="step-t">Select Transfer, enter amount, confirm PIN.</div></div>
    <div class="step-r"><div class="step-n" style="background:var(--gold);">3</div><div class="step-t">Come back here and tap Record Withdrawal to update vault.</div></div>
    <div style="font-size:10px;color:var(--blue);font-weight:800;letter-spacing:1px;text-transform:uppercase;margin:12px 0 8px;">Option 3 - OPay / PalmPay / Kuda</div>
    <div class="step-r"><div class="step-n" style="background:var(--blue);">1</div><div class="step-t">Open OPay (*955#), PalmPay (*945#), or Kuda app.</div></div>
    <div class="step-r"><div class="step-n" style="background:var(--blue);">2</div><div class="step-t">Transfer money out, then tap Record Withdrawal below.</div></div>
    <button class="btn bg" style="margin-top:16px;" onclick="hideWd();openModal('withdraw')">Record Withdrawal in Vault</button>
    <button class="btn bo" style="margin-top:8px;" onclick="hideWd()">Close</button>
  </div>
</div>

<script>
// ===================== STATE =====================
var chatHistory=[], mMode='deposit', budgetML=null, linkedAcct=null, GOAL=5000;
var allBanks=[], selCode='', selName='', vData=null, lastRef=null, vDepRef=null;

// ===================== TABS =====================
function goTab(id,n){
  document.querySelectorAll('.page').forEach(function(p){p.classList.remove('active');});
  document.querySelectorAll('.tab').forEach(function(t){t.classList.remove('active');});
  document.getElementById(id).classList.add('active');
  document.getElementById('t'+n).classList.add('active');
  if(id==='pg-vault') loadVault();
  if(id==='pg-bank')  initBank();
  if(id==='pg-game')  { setTimeout(initGame,80); }
}

// ===================== HELPERS =====================
function fN(n){return 'N'+Math.round(Math.max(0,n)).toLocaleString();}
function fT(t){
  return (t||'').replace(/\\*\\*(.*?)\\*\\*/g,'<b>$1</b>')
    .replace(/\\n/g,'<br>').replace(/(N[\\d,]+)/g,'<span class="nr">$1</span>');
}
function show(id){var e=document.getElementById(id);if(e)e.style.display='block';}
function hide(id){var e=document.getElementById(id);if(e)e.style.display='none';}
function scCol(s){return s>=70?'var(--accent)':s>=40?'var(--gold)':'var(--red)';}
function toSc(r){
  if(r<=0)return Math.max(0,parseInt(10+r*2));
  else if(r<=5)return parseInt(10+r*4);
  else if(r<=10)return parseInt(30+(r-5)*4);
  else if(r<=20)return parseInt(50+(r-10)*2.5);
  else return Math.min(100,parseInt(75+(r-20)*1.25));
}
function setScore(s){
  var e=document.getElementById('hScore'),t=document.getElementById('hTag');
  e.textContent=s;
  if(s>=70){e.style.color='var(--accent)';t.textContent='Great';t.style.color='var(--accent)';}
  else if(s>=40){e.style.color='var(--gold)';t.textContent='Average';t.style.color='var(--gold)';}
  else{e.style.color='var(--red)';t.textContent='Needs Work';t.style.color='var(--red)';}
}
function v(id){return parseFloat(document.getElementById(id).value)||0;}

// ===================== BUDGET =====================
function liveUp(){
  var inc=v('b_inc'),food=v('b_food'),tra=v('b_tra'),air=v('b_air'),oth=v('b_oth');
  var spent=food+tra+air+oth,save=inc-spent,rate=inc>0?(save/inc*100):0;
  document.getElementById('analyseBtn').disabled=(inc<=0);
  if(inc>0){
    show('liveSummary');
    document.getElementById('liveSpent').textContent=fN(spent);
    document.getElementById('liveSave').textContent=fN(save);
    document.getElementById('liveSave').style.color=save>=0?'var(--accent)':'var(--red)';
    var sc=toSc(rate),col=scCol(sc);
    document.getElementById('liveScore').textContent='Score: '+sc+'/100';
    document.getElementById('liveScore').style.color=col;
    document.getElementById('liveBar').style.width=Math.min(100,Math.max(0,rate*2))+'%';
    document.getElementById('liveBar').style.background=col;
  } else hide('liveSummary');
}
async function doAnalyse(){
  var inc=v('b_inc'),food=v('b_food'),tra=v('b_tra'),air=v('b_air'),oth=v('b_oth');
  if(!inc)return;
  var btn=document.getElementById('analyseBtn'); btn.textContent='Analysing...'; btn.disabled=true;
  var r=await fetch('/ml',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({nums:[inc,food,tra,air,oth]})});
  var m=await r.json(); budgetML=m; setScore(m.score);
  show('resultPanel');
  var sc=m.score,col=scCol(sc);
  var grade=sc>=70?'Excellent Saver!':sc>=50?'Good Saver':sc>=30?'Average Saver':'Needs Improvement';
  var desc=sc>=70?'You save more than most Nigerians at your income.':
           sc>=50?'Decent savings. A few tweaks and you will be excellent.':
           sc>=30?'You save a little. Much more potential here.':
                  'Most income going out. Let us find where to cut.';
  document.getElementById('scoreCircle').style.background=col;
  document.getElementById('scoreCircle').style.boxShadow='0 0 22px '+col;
  document.getElementById('rScoreNum').textContent=sc;
  document.getElementById('rGrade').textContent=grade;
  document.getElementById('rDesc').textContent=desc;
  document.getElementById('rActual').textContent=fN(m.actual);
  document.getElementById('rActual').style.color=m.actual>=0?'var(--accent)':'var(--red)';
  document.getElementById('rTarget').textContent=fN(m.ideal);
  document.getElementById('rRate').textContent=m.rate+'%';
  document.getElementById('rPeer').textContent=m.peer_avg?fN(m.peer_avg):'N/A';
  document.getElementById('rScoreBar').style.width=sc+'%';
  document.getElementById('rScoreBar').style.background=col;
  document.getElementById('rBarLbl').textContent=sc+'/100';
  document.getElementById('rBarLbl').style.color=col;
  var total=food+tra+air+oth||1;
  var cats=[{n:'Food',v:food,c:'var(--gold)'},{n:'Transport',v:tra,c:'var(--blue)'},
            {n:'Airtime',v:air,c:'var(--purple)'},{n:'Other',v:oth,c:'var(--red)'}];
  document.getElementById('spendBars').innerHTML=cats.map(function(c){
    var p=Math.round(c.v/total*100),pi=inc>0?Math.round(c.v/inc*100):0;
    return '<div class="spr"><span class="sn">'+c.n+'</span><div class="sbw"><div class="sb"><div class="sbf" style="width:'+p+'%;background:'+c.c+';"></div></div></div><span class="sp" style="color:'+c.c+'">'+pi+'%</span></div>';
  }).join('');
  var tips={Food:'Cook at home, buy from market in bulk - cuts food cost by 30%.',
            Transport:'Carpool, walk short distances, use keke instead of taxi.',
            Airtime:'Switch to weekly data bundles. Compare MTN, Glo, Airtel rates.',
            Other:'Track this category for 7 days. Most people find big surprises.'};
  document.getElementById('rAdvice').textContent='Biggest spend: '+m.leak+'. '+(tips[m.leak]||'Track this first.');
  show('aiBox');
  document.getElementById('aiText').innerHTML='<div class="typing-dots"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>';
  await fetch('/ml-memory',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({inc:inc,food:food,tra:tra,air:air,oth:oth,score:sc,savings:m.actual})});
  try{
    var cr=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({history:[{role:'user',content:'My budget this month: Income N'+inc+', Food N'+food+', Transport N'+tra+', Airtime N'+air+', Other N'+oth+'. I saved N'+Math.round(m.actual)+' which is '+m.rate+'%. My savings score is '+sc+'/100.'}]})});
    var cd=await cr.json();
    document.getElementById('aiText').innerHTML=fT(cd.reply||'Analysis complete.');
  } catch(e){
    document.getElementById('aiText').textContent='AI advice unavailable. Check your Anthropic API credits at console.anthropic.com';
  }
  document.getElementById('resultPanel').scrollIntoView({behavior:'smooth',block:'start'});
  btn.textContent='Analyse with AI'; btn.disabled=false;
}
function saveRec(){if(budgetML&&budgetML.target>0)qDeposit(budgetML.target,'Budget Savings');}
function sendBudgetToBank(){
  if(!linkedAcct){alert('Link a bank account in the Bank tab first.');goTab('pg-bank',2);return;}
  document.getElementById('sendAmt').value=budgetML?budgetML.target:'';
  document.getElementById('sendNote').value='Tanadi Monthly Savings';
  goTab('pg-bank',2);
}

// ===================== CHAT =====================
function addMsg(role,html){
  var el=document.getElementById('chatMsgs');
  var d=document.createElement('div'); d.className='msg '+(role==='user'?'user':'bot');
  var bub='<div class="bub">'+html+'</div>';
  d.innerHTML=role==='bot'?'<div class="av">N</div>'+bub:bub+'<div class="av">U</div>';
  el.appendChild(d); el.scrollTop=el.scrollHeight;
}
function showTyping(){
  var el=document.getElementById('chatMsgs');
  var d=document.createElement('div'); d.className='msg bot'; d.id='ctyp';
  d.innerHTML='<div class="av">N</div><div class="bub"><div class="typing-dots"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div></div>';
  el.appendChild(d); el.scrollTop=el.scrollHeight;
}
function rmTyping(){var t=document.getElementById('ctyp');if(t)t.remove();}

{{ js_brain | safe }}

function clearChat(){
  if(!confirm('Clear all chat history? This cannot be undone.')) return;
  chatHistory=[];
  var box=document.getElementById('chatBox');
  // Remove all messages except the first welcome message
  var msgs=box.querySelectorAll('.msg');
  msgs.forEach(function(m){m.remove();});
  fetch('/clear-chat',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).catch(function(){});
  addMsg('bot','<p>Chat cleared! I am Tanadi, your AI assistant. Ask me anything — savings, science, health, technology, relationships, or any topic!</p>');
}
async function chatSend(text){
  var inp=document.getElementById('chatTxt');
  var msg=text||inp.value.trim(); if(!msg)return;
  inp.value=''; inp.style.height='auto';
  document.getElementById('chatBtn').disabled=true;
  addMsg('user','<p>'+msg+'</p>');
  chatHistory.push({role:'user',content:msg});
  showTyping();
  document.getElementById('cstat').textContent='Thinking...';
  document.getElementById('cstat').style.color='var(--accent)';
  var rep='';
  try{
    var r=await fetch('/chat',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({history:chatHistory})
    });
    if(!r.ok) throw new Error('HTTP '+r.status);
    var d=await r.json();
    rep=(d&&d.reply)?d.reply:'';
  } catch(e){ rep=''; }
  rmTyping();
  if(!rep||rep.length<2) rep=jsReply(msg);
  addMsg('bot','<p>'+fT(rep)+'</p>');
  chatHistory.push({role:'assistant',content:rep});
  try{
    await fetch('/chat-memory',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({q:msg,a:rep})});
  } catch(e){}
  document.getElementById('cstat').textContent='';
  document.getElementById('chatBtn').disabled=false;
}
function hs(el){chatSend(el.textContent);}
document.getElementById('chatTxt').addEventListener('keydown',function(e){
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();chatSend();}
});
document.getElementById('chatTxt').addEventListener('input',function(){
  this.style.height='auto'; this.style.height=Math.min(this.scrollHeight,80)+'px';
});

// ===================== BANK =====================
async function initBank(){
  // Load key status
  try{
    var kr=await fetch('/key-status'); var kd=await kr.json();
    document.getElementById('keyWarn').style.display=kd.ps_ok?'none':'block';
  } catch(e){ /* ignore */ }
  if(linkedAcct){ showLinked(linkedAcct); return; }
  hide('bankLinked'); show('bankUnlinked');
  // Load banks if not loaded
  if(!allBanks.length){
    var sel=document.getElementById('bankSel');
    sel.innerHTML='<option value="">-- Loading... --</option>';
    try{
      var r=await fetch('/banks');
      var d=await r.json();
      allBanks=d.banks||[];
    } catch(e){
      // Use hardcoded fallback if fetch fails
      allBanks=[
        {name:"GTBank",code:"058"},{name:"Access Bank",code:"044"},
        {name:"First Bank of Nigeria",code:"011"},{name:"UBA",code:"033"},
        {name:"Zenith Bank",code:"057"},{name:"Fidelity Bank",code:"070"},
        {name:"OPay",code:"999992"},{name:"PalmPay",code:"999991"},
        {name:"Kuda Bank",code:"090267"},{name:"Moniepoint MFB",code:"090405"},
        {name:"Sterling Bank",code:"232"},{name:"Union Bank",code:"032"},
        {name:"Ecobank Nigeria",code:"050"},{name:"Stanbic IBTC",code:"221"},
        {name:"Carbon",code:"565"},{name:"Wema Bank",code:"035"},
        {name:"9PSB",code:"120001"},{name:"Polaris Bank",code:"076"},
        {name:"Heritage Bank",code:"030"},{name:"Keystone Bank",code:"082"},
        {name:"VFD MFB",code:"566"},{name:"FCMB",code:"214"},
        {name:"Jaiz Bank",code:"301"},{name:"Coronation Bank",code:"559"},
        {name:"Standard Chartered",code:"068"},{name:"Citibank",code:"023"},
      ];
    }
    sel.innerHTML='<option value="">-- Select your bank --</option>';
    allBanks.sort(function(a,b){return a.name.localeCompare(b.name);});
    allBanks.forEach(function(b){
      var o=document.createElement('option'); o.value=b.code; o.textContent=b.name; sel.appendChild(o);
    });
  }
}
function showLinked(acct){
  linkedAcct=acct; hide('bankUnlinked'); show('bankLinked');
  document.getElementById('bkBank').textContent=acct.bank_name;
  document.getElementById('bkNum').textContent=acct.account_number;
  document.getElementById('bkName').textContent=acct.account_name;
  loadBal();
}
async function loadBal(){
  document.getElementById('psBal').textContent='Loading...';
  try{
    var r=await fetch('/ps-balance'); var d=await r.json();
    document.getElementById('psBal').textContent=d.ok?fN(d.balance):'N0 (fund at paystack.com)';
  } catch(e){ document.getElementById('psBal').textContent='N/A'; }
}
function onBankChange(){
  var sel=document.getElementById('bankSel');
  selCode=sel.value; selName=sel.options[sel.selectedIndex]?sel.options[sel.selectedIndex].text:'';
  hide('testLimitBox'); tryV();
}
function onAcctIn(){
  vData=null; document.getElementById('linkBtn').disabled=true;
  hide('vname'); document.getElementById('vstatus').textContent='';
  var n=document.getElementById('acctNo').value.replace(/\\D/g,'');
  if(n.length===10&&selCode)startV(n);
}
var vt=null;
function tryV(){var n=document.getElementById('acctNo').value.replace(/\\D/g,'');if(n.length===10&&selCode)startV(n);}
function startV(n){
  clearTimeout(vt);
  document.getElementById('vstatus').innerHTML='<span style="color:var(--muted)">Verifying account...</span>';
  vt=setTimeout(async function(){
    try{
      var r=await fetch('/verify-account',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({account_number:n,bank_code:selCode})});
      var d=await r.json();
      if(d.ok){
        document.getElementById('vstatus').innerHTML='<span class="sok">Auto-verified successfully!</span>';
        document.getElementById('vname').textContent=d.name;
        show('vname');
        // Auto-fill the name field
        document.getElementById('manualName').value=d.name;
        document.getElementById('linkBtn').disabled=false;
        hide('testLimitBox');
        vData={account_number:n,bank_code:selCode,bank_name:selName,account_name:d.name};
      } else {
        var msg=d.msg||'';
        document.getElementById('vstatus').innerHTML='<span class="serr">'+msg+'</span>';
        if(msg.toLowerCase().indexOf('limit')>=0||msg.toLowerCase().indexOf('test')>=0){
          show('testLimitBox');
        }
        document.getElementById('linkBtn').disabled=true;
        document.getElementById('vstatus2').innerHTML='<span style="color:var(--gold);font-size:11px;">Auto-verify failed. Enter your account name below and tap Manual Link.</span>';
      }
    } catch(e){
      document.getElementById('vstatus').innerHTML='<span class="serr">Network error. Check internet connection.</span>';
    }
  },800);
}
function linkAcct(){
  if(vData){showLinked(vData);return;}
  // Try using filled fields
  var n=document.getElementById('acctNo').value.replace(/\D/g,'');
  var name=document.getElementById('manualName').value.trim().toUpperCase();
  if(n&&n.length===10&&selCode&&name){
    showLinked({account_number:n,bank_code:selCode,bank_name:selName,account_name:name});
  }
}
function linkManual(){
  var n=document.getElementById('acctNo').value.replace(/\\D/g,'');
  var name=document.getElementById('manualName').value.trim().toUpperCase();
  if(!n||n.length!==10){alert('Please enter your 10-digit account number first.');return;}
  if(!selCode){alert('Please select your bank first.');return;}
  if(!name||name.length<3){alert('Please enter your full account name (as on your bank card).');return;}
  showLinked({account_number:n,bank_code:selCode,bank_name:selName,account_name:name});
}
function unlinkBank(){linkedAcct=null;vData=null;hide('bankLinked');show('bankUnlinked');}
async function doSend(){
  var amt=parseFloat(document.getElementById('sendAmt').value);
  var note=document.getElementById('sendNote').value||'Tanadi Savings';
  if(!amt||amt<=0)return;
  var res=document.getElementById('sendRes'); show('sendRes');
  res.className='rbox rinfo'; res.textContent='Processing transfer...';
  var r=await fetch('/transfer',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({amount:amt,account_number:linkedAcct.account_number,
      bank_code:linkedAcct.bank_code,bank_name:linkedAcct.bank_name,
      account_name:linkedAcct.account_name,note:note})});
  var d=await r.json();
  if(d.ok){
    res.className='rbox rok';
    res.innerHTML='Transfer sent! Ref: '+(d.ref||'N/A')+'<br>Status: '+(d.status||'pending');
    await fetch('/vault/withdraw',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({amount:amt,note:'Sent to '+linkedAcct.bank_name})});
    loadVault();
  } else {
    res.className='rbox rerr';
    res.innerHTML=d.msg;
  }
}
async function doReceive(){
  var amt=parseFloat(document.getElementById('recvAmt').value);
  var email=document.getElementById('recvEmail').value.trim();
  if(!amt||!email){alert('Enter amount and email.');return;}
  var ref='tanadi-rcv-'+Date.now(); lastRef=ref;
  var res=document.getElementById('recvRes'); show('recvRes');
  res.className='rbox rinfo'; res.textContent='Generating payment link...';
  var r=await fetch('/init-payment',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({amount:amt,email:email,ref:ref})});
  var d=await r.json();
  if(d.ok){
    res.className='rbox rok';
    res.innerHTML='Payment link ready!<br><a href="'+d.url+'" target="_blank" style="color:var(--accent);font-weight:800;font-size:14px;">Open Payment Page ('+fN(amt)+')</a><br><small style="color:var(--muted)">After paying tap Verify below</small>';
  } else { res.className='rbox rerr'; res.textContent=d.msg; }
}
async function doVerifyPay(){
  if(!lastRef){alert('Generate a payment link first.');return;}
  var res=document.getElementById('recvRes'); show('recvRes');
  res.className='rbox rinfo'; res.textContent='Verifying payment...';
  var r=await fetch('/verify-payment',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ref:lastRef})});
  var d=await r.json();
  if(d.ok){
    res.className='rbox rok';
    res.innerHTML=fN(d.amount)+' received and added to vault!';
    loadVault();
  } else { res.className='rbox rerr'; res.textContent=d.msg; }
}

// ===================== VAULT =====================
function checkVDep(){
  var amt=parseFloat(document.getElementById('vDepAmt').value)||0;
  var email=document.getElementById('vDepEmail').value.trim();
  document.getElementById('vDepBtn').disabled=!(amt>0&&email.includes('@'));
}
async function vaultPay(){
  var amt=parseFloat(document.getElementById('vDepAmt').value);
  var email=document.getElementById('vDepEmail').value.trim();
  if(!amt||!email)return;
  var ref='vault-dep-'+Date.now(); vDepRef=ref;
  var res=document.getElementById('vDepRes'); show('vDepRes');
  res.className='rbox rinfo'; res.textContent='Creating payment link...';
  var r=await fetch('/init-payment',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({amount:amt,email:email,ref:ref})});
  var d=await r.json();
  if(d.ok){
    res.className='rbox rok';
    res.innerHTML='Payment link ready!<br><a href="'+d.url+'" target="_blank" style="color:var(--accent);font-size:15px;font-weight:800;">Pay '+fN(amt)+' here</a><br><small style="color:var(--muted)">Card, bank transfer, or USSD. After paying tap button below.</small>';
    document.getElementById('vVerBtn').style.display='block';
  } else { res.className='rbox rerr'; res.textContent=d.msg; }
}
async function vaultVerify(){
  if(!vDepRef)return;
  var res=document.getElementById('vDepRes');
  res.className='rbox rinfo'; res.textContent='Verifying payment...';
  var r=await fetch('/verify-payment',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ref:vDepRef})});
  var d=await r.json();
  if(d.ok){
    res.className='rbox rok'; res.innerHTML=fN(d.amount)+' added to your vault!';
    document.getElementById('vVerBtn').style.display='none'; vDepRef=null; loadVault();
  } else { res.className='rbox rerr'; res.textContent=d.msg+' - try again in a moment.'; }
}
async function loadVault(){
  try{
    var r=await fetch('/vault'); var d=await r.json();
    document.getElementById('vBal').textContent=d.balance.toLocaleString();
    var pct=Math.min(100,(d.balance/GOAL*100)).toFixed(0);
    document.getElementById('vPct').textContent=pct+'%';
    document.getElementById('vBar').style.width=pct+'%';
    document.getElementById('vSub').textContent=
      d.balance>=GOAL?'Goal reached! Congratulations!':fN(GOAL-d.balance)+' to reach N5,000 goal';
    var txEl=document.getElementById('txList');
    if(!d.transactions.length){txEl.innerHTML='<div class="empty">No transactions yet.<br>Make your first deposit!</div>';return;}
    txEl.innerHTML=d.transactions.slice().reverse().map(function(t){
      var cls=t.type==='deposit'?'dep':t.type==='received'?'rcv':'wit';
      var ico=t.type==='deposit'||t.type==='received'?'+':'-';
      return '<div class="txr '+cls+'"><div class="txl"><div class="txi">'+ico+'</div><div><div class="txn">'+t.note+'</div><div class="txd">'+t.date+'</div></div></div><div class="txa">'+(t.type!=='wit'?'+':'-')+fN(t.amount)+'</div></div>';
    }).join('');
  } catch(e){}
}
function openModal(m){
  mMode=m;
  document.getElementById('mTitle').textContent=m==='deposit'?'Deposit to Vault':'Record Withdrawal';
  document.getElementById('mAmt').value=''; document.getElementById('mNote').value='';
  document.getElementById('modal').classList.add('open');
  setTimeout(function(){document.getElementById('mAmt').focus();},150);
}
function closeModal(){document.getElementById('modal').classList.remove('open');}
async function doModal(){
  var amt=parseFloat(document.getElementById('mAmt').value);
  var note=document.getElementById('mNote').value||(mMode==='deposit'?'Manual Deposit':'Withdrawal');
  if(!amt||amt<=0)return;
  await fetch('/vault/'+mMode,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({amount:amt,note:note})});
  closeModal(); loadVault();
}
async function qDeposit(amount,note){
  if(!amount||amount<=0)return;
  await fetch('/vault/deposit',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({amount:amount,note:note||'Savings'})});
  goTab('pg-vault',3); loadVault();
}
function showWd(){document.getElementById('wdGuide').classList.add('open');}
function hideWd(){document.getElementById('wdGuide').classList.remove('open');}

// ===================== NAIRA RUNNER GAME =====================
var kL=false, kR=false;
var G={on:false,score:0,coins:0,lives:3,best:0,level:1,speed:3,frame:0,raf:null,started:false};
var P={x:70,y:0,vy:0,w:24,h:32,ground:true};
var OBS=[], COINS=[], PARTS=[];
var CX,CW,CH,GND;

function initGame(){
  var cv=document.getElementById('gameCanvas');
  if(!cv)return;
  CX=cv.getContext('2d');
  var wrap=cv.parentElement;
  CW=wrap.clientWidth||360;
  CH=wrap.clientHeight||200;
  cv.width=CW; cv.height=CH;
  cv.style.width=CW+'px'; cv.style.height=CH+'px';
  GND=CH-36;
  P.y=GND-P.h;
  if(!G.started) drawTitle();
}

function drawTitle(){
  if(!CX)return;
  CX.fillStyle='#0a1628'; CX.fillRect(0,0,CW,CH);
  // Title
  CX.fillStyle='#00d4aa';
  CX.font='bold 22px Nunito,sans-serif'; CX.textAlign='center';
  CX.fillText('NAIRA RUNNER',CW/2,CH/2-50);
  CX.fillStyle='#e0eefa';
  CX.font='13px Nunito,sans-serif';
  CX.fillText('Collect coins. Avoid debt traps!',CW/2,CH/2-22);
  // Draw character preview
  drawPlayer(CW/2-12, CH/2+5, 0);
  // Coin preview
  CX.beginPath(); CX.arc(CW/2+30,CH/2+15,10,0,Math.PI*2);
  var cg=CX.createRadialGradient(CW/2+30,CH/2+15,2,CW/2+30,CH/2+15,10);
  cg.addColorStop(0,'#fbbf24'); cg.addColorStop(1,'#d97706'); CX.fillStyle=cg; CX.fill();
  CX.fillStyle='#92400e'; CX.font='bold 9px Arial'; CX.textAlign='center';
  CX.fillText('N',CW/2+30,CH/2+19);
  // Obstacle preview
  CX.fillStyle='#f05252'; CX.beginPath();
  CX.roundRect(CW/2+55,CH/2+5,22,30,4); CX.fill();
  CX.font='12px Arial'; CX.textAlign='center';
  CX.fillText('D',CW/2+66,CH/2+24);
  CX.fillStyle='#4d7299'; CX.font='11px Nunito,sans-serif'; CX.textAlign='center';
  CX.fillText('Tap JUMP to start!',CW/2,CH/2+55);
}

function startGame(){
  G.on=true; G.started=true; G.score=0; G.coins=0; G.lives=3;
  G.level=1; G.speed=3; G.frame=0;
  P.x=70; P.y=GND-P.h; P.vy=0; P.ground=true;
  OBS=[]; COINS=[]; PARTS=[];
  updateHUD();
  if(G.raf) cancelAnimationFrame(G.raf);
  loop();
}

function doJump(){
  if(!G.started||!G.on){startGame();return;}
  if(P.ground){P.vy=-12; P.ground=false;}
}

function loop(){
  if(!G.on)return;
  G.raf=requestAnimationFrame(loop);
  G.frame++;
  G.score=Math.floor(G.frame/5);
  // Level up every 300 score
  G.level=Math.floor(G.score/300)+1;
  G.speed=3+Math.min(6,(G.level-1)*0.7);
  // Spawn obstacles
  var spawnRate=Math.max(45,90-G.frame/60);
  if(G.frame%Math.floor(spawnRate)===0) spawnObs();
  // Spawn coins
  if(G.frame%50===0) spawnCoin();
  // Move player
  if(kL&&P.x>20) P.x-=4;
  if(kR&&P.x<CW*0.4) P.x+=4;
  // Gravity
  P.vy+=0.55; P.y+=P.vy;
  if(P.y>=GND-P.h){P.y=GND-P.h; P.vy=0; P.ground=true;}
  else P.ground=false;
  // Obstacles
  for(var i=OBS.length-1;i>=0;i--){
    OBS[i].x-=G.speed;
    if(OBS[i].x+OBS[i].w<0){OBS.splice(i,1);continue;}
    if(!OBS[i].hit&&rectsHit(P,OBS[i])){
      OBS[i].hit=true; burst(OBS[i].x,OBS[i].y,'#f05252');
      G.lives--; updateHUD();
      if(G.lives<=0){gameOver();return;}
    }
  }
  // Coins
  for(var j=COINS.length-1;j>=0;j--){
    COINS[j].x-=G.speed;
    if(COINS[j].x<-20){COINS.splice(j,1);continue;}
    if(!COINS[j].hit&&circHit(COINS[j],P)){
      COINS[j].hit=true; burst(COINS[j].x,COINS[j].y,'#00d4aa');
      G.coins++; COINS.splice(j,1); updateHUD();
    }
  }
  // Particles
  for(var p=PARTS.length-1;p>=0;p--){
    var pt=PARTS[p];
    pt.x+=pt.vx; pt.y+=pt.vy; pt.vy+=0.25; pt.life--;
    if(pt.life<=0) PARTS.splice(p,1);
  }
  draw();
}

function spawnObs(){
  var h=28+Math.floor(Math.random()*30);
  var types=['D','B','T']; // Debt, Bill, Tax
  OBS.push({x:CW+10,y:GND-h,w:24,h:h,hit:false,t:types[Math.floor(Math.random()*types.length)]});
}
function spawnCoin(){
  var yOff=50+Math.floor(Math.random()*55);
  COINS.push({x:CW+10,y:GND-yOff,r:11,hit:false});
}
function burst(x,y,col){
  for(var i=0;i<8;i++){
    var a=Math.random()*Math.PI*2;
    var sp=2+Math.random()*4;
    PARTS.push({x:x,y:y,vx:Math.cos(a)*sp,vy:Math.sin(a)*sp-2,life:22,col:col});
  }
}
function rectsHit(a,b){
  return a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y;
}
function circHit(c,r){
  var cx=Math.max(r.x,Math.min(c.x,r.x+r.w));
  var cy=Math.max(r.y,Math.min(c.y,r.y+r.h));
  return Math.sqrt((c.x-cx)**2+(c.y-cy)**2)<c.r;
}

function drawPlayer(x,y,frame){
  // body
  CX.fillStyle='#00d4aa';
  CX.beginPath(); CX.rect(x+3,y+10,18,18);
  CX.fill();
  // head
  CX.fillStyle='#fde68a'; CX.beginPath(); CX.arc(x+12,y+7,7,0,Math.PI*2); CX.fill();
  // eye
  CX.fillStyle='#1e293b'; CX.beginPath(); CX.arc(x+15,y+6,1.5,0,Math.PI*2); CX.fill();
  // N on shirt
  CX.fillStyle='#fff'; CX.font='bold 9px Arial'; CX.textAlign='center';
  CX.fillText('N',x+12,y+22);
  // legs
  var lk=(frame&&G.on)?Math.sin(G.frame*0.35)*7:0;
  CX.strokeStyle='#00b894'; CX.lineWidth=4; CX.lineCap='round';
  CX.beginPath(); CX.moveTo(x+8,y+28); CX.lineTo(x+8,y+33+lk); CX.stroke();
  CX.beginPath(); CX.moveTo(x+16,y+28); CX.lineTo(x+16,y+33-lk); CX.stroke();
}

function draw(){
  CX.clearRect(0,0,CW,CH);
  // Sky
  var sky=CX.createLinearGradient(0,0,0,CH);
  sky.addColorStop(0,'#07101f'); sky.addColorStop(1,'#0f2040');
  CX.fillStyle=sky; CX.fillRect(0,0,CW,CH);
  // Stars
  for(var s=0;s<18;s++){
    CX.fillStyle='rgba(255,255,255,'+(0.2+Math.sin(s+G.frame*0.01)*0.15)+')';
    CX.fillRect((s*137+G.frame*0.3)%CW,(s*89)%(GND-10),1.5,1.5);
  }
  // Buildings bg
  for(var b=0;b<4;b++){
    var bx=((b*140-(G.frame*G.speed*0.15))%CW+CW)%CW;
    var bh=40+b*15;
    CX.fillStyle='rgba(15,28,46,0.9)';
    CX.fillRect(bx,GND-bh,50,bh);
    // windows
    CX.fillStyle='rgba(244,169,22,0.3)';
    for(var w=0;w<3;w++) for(var ww=0;ww<2;ww++)
      CX.fillRect(bx+8+ww*18,GND-bh+8+w*12,8,7);
  }
  // Ground
  CX.fillStyle='#1c3454'; CX.fillRect(0,GND,CW,CH-GND);
  CX.fillStyle='#00d4aa'; CX.fillRect(0,GND,CW,2);
  // Ground dashes
  CX.strokeStyle='rgba(0,212,170,0.15)'; CX.lineWidth=1;
  for(var d=0;d<6;d++){
    var dx=((d*100-(G.frame*G.speed)%100)+100)%CW;
    CX.beginPath(); CX.moveTo(dx,GND+6); CX.lineTo(dx,CH); CX.stroke();
  }
  // Obstacles
  OBS.forEach(function(ob){
    if(ob.hit)return;
    var col=ob.t==='D'?'#f05252':ob.t==='B'?'#f4a916':'#a855f7';
    CX.fillStyle=col;
    CX.beginPath(); CX.rect(ob.x,ob.y,ob.w,ob.h);
    CX.fill();
    // Label
    CX.fillStyle='rgba(0,0,0,0.5)'; CX.fillRect(ob.x,ob.y,ob.w,16);
    CX.fillStyle='#fff'; CX.font='bold 10px Arial'; CX.textAlign='center';
    var lbl=ob.t==='D'?'DEBT':ob.t==='B'?'BILL':'TAX';
    CX.fillText(lbl,ob.x+ob.w/2,ob.y+11);
  });
  // Coins
  COINS.forEach(function(ci){
    if(ci.hit)return;
    CX.save(); CX.translate(ci.x,ci.y);
    var pulse=1+Math.sin(G.frame*0.2)*0.12;
    CX.scale(pulse,pulse);
    var cg=CX.createRadialGradient(0,0,2,0,0,ci.r);
    cg.addColorStop(0,'#fde68a'); cg.addColorStop(0.7,'#f59e0b'); cg.addColorStop(1,'#b45309');
    CX.fillStyle=cg; CX.beginPath(); CX.arc(0,0,ci.r,0,Math.PI*2); CX.fill();
    CX.strokeStyle='rgba(255,255,255,0.3)'; CX.lineWidth=1; CX.stroke();
    CX.fillStyle='#78350f'; CX.font='bold 9px Arial'; CX.textAlign='center';
    CX.fillText('N',0,3); CX.restore();
  });
  // Player
  drawPlayer(P.x, P.y, G.frame);
  // Particles
  PARTS.forEach(function(pt){
    CX.globalAlpha=pt.life/22;
    CX.fillStyle=pt.col;
    CX.beginPath(); CX.arc(pt.x,pt.y,4,0,Math.PI*2); CX.fill();
  });
  CX.globalAlpha=1;
  // HUD overlay hint
  if(G.frame<90){
    CX.fillStyle='rgba(0,212,170,0.6)'; CX.font='10px Nunito,sans-serif'; CX.textAlign='left';
    CX.fillText('Dodge DEBT BILL TAX  |  Collect N coins!',8,12);
  }
  // Level banner
  if(G.level>1&&G.frame%300<60){
    CX.fillStyle='rgba(168,85,247,0.8)'; CX.font='bold 14px Nunito,sans-serif'; CX.textAlign='center';
    CX.fillText('LEVEL '+G.level+'!',CW/2,30);
  }
}

function updateHUD(){
  document.getElementById('gScore').textContent=G.score;
  document.getElementById('gCoins').textContent=G.coins;
  document.getElementById('gLives').textContent=G.lives;
  document.getElementById('gBest').textContent=G.best;
  document.getElementById('gLevel').textContent=G.level;
}

function gameOver(){
  G.on=false;
  if(G.score>G.best) G.best=G.score;
  updateHUD();
  // Award coins to vault
  if(G.coins>0){
    fetch('/game-coins',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({coins:G.coins,score:G.score})});
  }
  // Draw game over screen
  CX.fillStyle='rgba(7,16,31,0.88)';
  CX.fillRect(0,0,CW,CH);
  CX.fillStyle='#f05252';
  CX.font='bold 24px Nunito,sans-serif'; CX.textAlign='center';
  CX.fillText('GAME OVER',CW/2,CH/2-55);
  CX.fillStyle='#e0eefa'; CX.font='14px Nunito,sans-serif';
  CX.fillText('Score: '+G.score,CW/2,CH/2-28);
  CX.fillStyle='#00d4aa';
  CX.fillText('Coins collected: '+G.coins,CW/2,CH/2-8);
  CX.fillStyle='#f4a916';
  CX.fillText('Best score: '+G.best,CW/2,CH/2+16);
  if(G.coins>0){
    CX.fillStyle='#a855f7';
    CX.fillText('N'+G.coins+' added to your vault!',CW/2,CH/2+40);
  }
  CX.fillStyle='#4d7299'; CX.font='12px Nunito,sans-serif';
  CX.fillText('Tap JUMP to play again',CW/2,CH/2+68);
}

// keyboard support
document.addEventListener('keydown',function(e){
  if(e.code==='ArrowLeft')kL=true;
  if(e.code==='ArrowRight')kR=true;
  if(e.code==='Space'||e.code==='ArrowUp'){e.preventDefault();doJump();}
});
document.addEventListener('keyup',function(e){
  if(e.code==='ArrowLeft')kL=false;
  if(e.code==='ArrowRight')kR=false;
});

// ===================== INIT =====================
addMsg('bot',
  '<p><b>Hello!</b> I am Tanadi, your personal savings coach.</p>'+
  '<p style="margin-top:8px;">I am here to help you save smarter. You can tell me your income and expenses and I will give you a full analysis. Or just ask me anything about saving money!</p>'+
  '<p style="margin-top:8px;font-size:12px;color:var(--muted);">Try: <span style="color:var(--accent);">I earn N7,000. Food N2,500, transport N800, airtime N400</span></p>'
);
</script>
</body>
</html>"""

@app.route("/")
def index(): return render_template_string(HTML, js_brain=JS_BRAIN)

@app.route("/key-status")
def key_status(): return jsonify({"ps_ok": has_ps(), "ant_ok": has_ant()})


def smart_answer(topic, original_msg):
    """Actually answer any topic intelligently - the universal brain."""
    import re
    t = (topic or original_msg or '').lower().strip()
    o = (original_msg or '').lower().strip()
    
    # === GRAMMAR & LANGUAGE ===
    if re.search(r'\b(noun|verb|adjective|adverb|pronoun|preposition|conjunction|interjection|part of speech|grammar|sentence|clause|phrase|syntax|tense|plural|singular|vocabulary|spelling|punctuation)\b', t):
        if 'noun' in t: return "A noun is a word that names a person, place, thing, or idea.\n\n📚 Types of nouns:\n- **Common noun**: general names (dog, city, table)\n- **Proper noun**: specific names (Lagos, Amaka, Nigeria) - always capitalised\n- **Collective noun**: group names (team, family, flock)\n- **Abstract noun**: ideas/feelings (love, freedom, happiness)\n- **Concrete noun**: physical things you can touch (book, water, phone)\n\nExamples in sentences:\n- 'The **girl** ran to **school**.' (person, place)\n- '**Honesty** is the best policy.' (abstract noun)\n\nNouns can be the subject or object of a sentence."
        if 'verb' in t: return "A verb is a word that shows action or state of being.\n\n📚 Types:\n- **Action verbs**: run, eat, write, sleep\n- **Linking verbs**: is, are, was, were, seem, become\n- **Helping/Auxiliary verbs**: have, had, will, would, can, could, should\n- **Transitive verbs**: take an object ('She **reads** a book')\n- **Intransitive verbs**: no object needed ('He **sleeps**')\n\nTenses change verbs:\n- Present: I eat / I am eating\n- Past: I ate / I was eating\n- Future: I will eat / I will be eating\n\nVerbs are the engine of every sentence!"
        if 'adjective' in t: return "An adjective is a word that describes or modifies a noun.\n\n📚 Examples:\n- 'The **tall** man' (describing man)\n- 'She is **beautiful**' (describing she)\n- '**Three** apples' (number as adjective)\n\nTypes:\n- Descriptive: big, small, hot, cold, beautiful\n- Quantitative: many, few, some, all, several\n- Demonstrative: this, that, these, those\n- Possessive: my, your, his, her, our\n- Interrogative: which, what, whose\n\nAdjectives usually come before the noun or after linking verbs."
        if 'adverb' in t: return "An adverb modifies a verb, adjective, or another adverb.\n\n📚 Examples:\n- 'She runs **quickly**.' (modifies verb)\n- 'He is **very** tall.' (modifies adjective)\n- 'She sings **quite** beautifully.' (modifies adverb)\n\nTypes:\n- Manner: quickly, slowly, carefully, well\n- Time: now, then, soon, yesterday, always\n- Place: here, there, everywhere, outside\n- Degree: very, too, quite, almost, enough\n- Frequency: always, never, often, sometimes\n\nMany adverbs end in -ly (quickly, honestly, beautifully)."
        if 'pronoun' in t: return "A pronoun replaces a noun to avoid repetition.\n\n📚 Types:\n- **Personal**: I, you, he, she, it, we, they, me, him, her, us, them\n- **Possessive**: my, your, his, her, its, our, their, mine, yours\n- **Reflexive**: myself, yourself, himself, herself, itself\n- **Relative**: who, whom, which, that, whose\n- **Demonstrative**: this, that, these, those\n- **Indefinite**: everyone, someone, anyone, nobody, all, each\n\nExample: Instead of 'Chidi went to market. Chidi bought yam.' we say 'Chidi went to market. **He** bought yam.'"
        return "Grammar is the set of rules that govern how we use language.\n\n📚 Main parts of speech in English:\n1. **Noun** - names (person, place, thing, idea)\n2. **Pronoun** - replaces nouns (he, she, they)\n3. **Verb** - actions or states (run, is, think)\n4. **Adjective** - describes nouns (big, beautiful)\n5. **Adverb** - modifies verbs/adjectives (quickly, very)\n6. **Preposition** - shows relationship (in, on, at, by)\n7. **Conjunction** - connects words/clauses (and, but, or, because)\n8. **Interjection** - expresses emotion (Oh! Wow! Ouch!)\n\nAsk me about any specific part of speech for a detailed explanation!"
    
    # === WHO AM I TO YOU ===
    if re.search(r'\b(who.*i.*to you|who am i|what.*am i|who are you to me|do you know me|remember me)\b', t+' '+o):
        return "You are my user and the most important person in this conversation! I am here 100% for you.\n\nWhile I do not store personal data between sessions, within our current conversation I remember everything you have told me. You are someone who cares about improving your life — financially and intellectually — and that makes you special.\n\nTo me, you are:\n💎 A valued user who deserves accurate, helpful answers\n🤝 Someone I genuinely want to help succeed\n🌟 A person with the potential to achieve great things\n\nWhat would you like to know or discuss today?"
    
    # === WHAT CAN YOU DO ===
    if re.search(r'\b(what.*can you do|what.*you.*do|your capabilities|what.*you.*capable|how.*you.*help|what.*you.*know|your abilities|your features)\b', t+' '+o):
        return "Here is everything I can do for you:\n\n💰 **Finance & Savings**\n- Analyse your income and expenses\n- Calculate your savings rate vs 10,000 Nigerian peers\n- Give personalised money-saving tips\n- Explain investments, banking, loans\n\n🧠 **General Knowledge**\n- Science (biology, chemistry, physics, astronomy)\n- Technology (AI, internet, coding, 5G)\n- Health (diseases, treatments, wellness)\n- History (Nigeria, Africa, World Wars)\n- Education (grammar, maths, economics)\n- Environment & climate change\n\n🇳🇬 **Nigerian Specific**\n- Banking apps (OPay, Kuda, Piggyvest)\n- USSD codes, Paystack, transfers\n- Nigerian history, politics, culture\n\n🌍 **Languages**\n- English, Pidgin, Hausa, Yoruba, Igbo, French\n\nJust ask me anything — I will answer!"
    
    # === MATHEMATICS ===
    if re.search(r'\b(math|mathematics|algebra|geometry|calculus|equation|formula|fraction|percentage|decimal|prime number|pythagorean|trigonometry|statistics|probability)\b', t):
        if 'pythagorean' in t or 'pythagoras' in t: return "The Pythagorean Theorem states that in a right-angled triangle: **a² + b² = c²** where c is the hypotenuse (longest side).\n\nExample: If two sides are 3 and 4, the hypotenuse = √(9+16) = √25 = **5**.\n\nThis theorem is used in:\n- Construction and engineering\n- Navigation and GPS\n- Computer graphics\n- Architecture (ensuring right angles)\n\nNamed after Greek mathematician Pythagoras (570-495 BC)."
        if 'percentage' in t or 'percent' in t: return "Percentage means 'per hundred' - it expresses a number as a fraction of 100.\n\n📐 **Formula:** Percentage = (Part ÷ Whole) × 100\n\nExamples:\n- 30 out of 50 = (30÷50) × 100 = **60%**\n- 20% of N5,000 = (20÷100) × 5,000 = **N1,000**\n\nUseful for savings: If you earn N7,000 and save N700, your savings rate = (700÷7000) × 100 = **10%** - that is the target minimum!"
        if 'fraction' in t: return "A fraction represents a part of a whole, written as numerator/denominator.\n\n📐 Types:\n- **Proper fraction**: numerator < denominator (3/4, 1/2)\n- **Improper fraction**: numerator > denominator (7/3, 9/4)\n- **Mixed number**: whole + fraction (2½, 3¾)\n\nOperations:\n- Add/Subtract: make denominators equal first\n- Multiply: multiply numerators, multiply denominators\n- Divide: flip the second fraction and multiply\n\nExample: ½ + ¼ = 2/4 + 1/4 = **3/4**"
        return "Mathematics is the science of numbers, patterns, and logical reasoning.\n\n📐 **Main branches:**\n- **Arithmetic**: basic operations (+, -, ×, ÷)\n- **Algebra**: equations with variables (x, y)\n- **Geometry**: shapes, angles, areas, volumes\n- **Statistics**: data, averages, probability\n- **Calculus**: rates of change, areas under curves\n\nKey formulas to know:\n- Area of circle: πr²\n- Area of rectangle: length × width\n- Pythagoras: a² + b² = c²\n- Simple interest: P × R × T / 100\n\nAsk me about any specific maths topic!"
    
    # === ECONOMICS specific ===
    if re.search(r'\b(supply.*demand|demand.*supply|market|price.*rise|trade|export|import|tax|budget.*government|fiscal|monetary policy|cbn|central bank|gdp|inflation rate)\b', t):
        return "Economics explains how markets work.\n\n📊 **Supply and Demand:**\n- When supply increases and demand stays same → prices fall\n- When demand increases and supply stays same → prices rise\n- Nigeria's fuel subsidy removal increased fuel prices because demand was high\n\n💰 **Key economic bodies in Nigeria:**\n- **CBN** (Central Bank of Nigeria): controls money supply and interest rates\n- **FIRS**: collects taxes\n- **NBS**: measures GDP and economic data\n\n📈 **Nigeria's economy:** Africa's largest at ~$477 billion GDP. Oil accounts for ~90% of export earnings but only 10% of GDP. Agriculture employs ~35% of Nigerians. Tech/fintech is the fastest-growing sector."
    
    # === GEOGRAPHY ===
    if re.search(r'\b(geography|country|continent|capital city|population|river|mountain|ocean|lake|map|latitude|longitude|equator)\b', t):
        if re.search(r'\b(capital.*nigeria|nigeria.*capital|abuja)\b', t+' '+o): return "Abuja is the capital city of Nigeria, located in the Federal Capital Territory (FCT). It became the capital in 1991, replacing Lagos. Population: approximately 3.6 million. Known for its planned layout, Aso Rock (the seat of government), the National Mosque, National Church, and Millennium Tower. It is centrally located to serve all geopolitical zones."
        if re.search(r'\b(africa.*capital|largest.*africa|continent)\b', t): return "Africa is the world's second-largest continent with 54 countries and 1.4+ billion people. Key facts:\n- Largest country by area: Algeria\n- Most populous: Nigeria (220m+)\n- Largest economy: Nigeria ($477bn GDP)\n- Longest river: Nile (Egypt/Uganda)\n- Highest mountain: Kilimanjaro (Tanzania) at 5,895m\n- Only continent spanning all four hemispheres"
        return "Geography studies the Earth's physical features, climate, and human populations.\n\n🌍 **Physical geography:** mountains, rivers, oceans, climate\n**Human geography:** cities, populations, cultures, economies\n\nNigeria's geography:\n- Area: 923,768 km² (32nd largest in world)\n- Borders: Benin, Niger, Chad, Cameroon\n- Major rivers: Niger, Benue (join at Lokoja)\n- Climate zones: Sahel (north) to tropical rainforest (south)\n- Natural resources: crude oil, natural gas, coal, tin, columbite\n\nAsk about any specific country or geographical topic!"
    
    # === PHILOSOPHY ===
    if re.search(r'\b(philosophy|meaning of life|ethics|morality|consciousness|existence|logic|epistemology|plato|aristotle|socrates|kant|wisdom|truth|knowledge)\b', t):
        return "Philosophy is the study of fundamental questions about existence, knowledge, values, and reason.\n\n🤔 **Major branches:**\n- **Metaphysics**: What is reality? What exists?\n- **Epistemology**: What is knowledge? How do we know?\n- **Ethics**: What is right and wrong?\n- **Logic**: What makes an argument valid?\n- **Political philosophy**: What is justice? How should society be governed?\n\n💡 **Famous ideas:**\n- Socrates: 'Know thyself' — self-awareness is wisdom\n- Plato: Reality is made of perfect 'Forms' our world copies\n- Aristotle: Virtue is the middle path between extremes\n- Descartes: 'I think, therefore I am'\n\nPhilosophy teaches critical thinking — one of the most valuable skills in any field!"
    
    # === RELIGION ===
    if re.search(r'\b(religion|islam|christianity|muslim|christian|prayer|god|allah|bible|quran|faith|worship|mosque|church|ramadan|christmas|eid)\b', t):
        return "Religion is a deeply personal and important part of life for most Nigerians.\n\n🕌 **Nigeria's religious landscape:**\n- Christianity: ~50% (predominantly in South)\n- Islam: ~47% (predominantly in North)\n- Traditional religions: ~3%\n\n✝️ **Christianity in Nigeria:** Largest denominations: Catholic, Anglican, Pentecostal (Redeemed, Winners Chapel, Living Faith). Nigeria has some of the largest churches in the world.\n\n☪️ **Islam in Nigeria:** Sunni Islam is predominant. The Sultan of Sokoto is the spiritual leader. Key events: Ramadan (fasting month), Eid al-Fitr, Eid al-Adha.\n\nBoth religions emphasise honesty, hard work, charity, and community — values that align well with good financial habits and saving for the future."
    
    # === TECHNOLOGY specific ===
    if re.search(r'\b(computer|how.*computer|hardware|software|processor|ram|storage|operating system|windows|android|ios|app|database|server|cloud)\b', t):
        if 'android' in t: return "Android is Google's mobile operating system, running on most smartphones worldwide including all Pydroid 3 devices.\n\n📱 **Key features:**\n- Open source - manufacturers can customise it\n- Google Play Store for apps\n- Supports multiple apps simultaneously\n- Regular security updates\n\n**Android versions:** Named after desserts until Android 10 (now just numbers). Latest: Android 15 (2024).\n\n**For Nigerian users:** Android dominates Nigeria's smartphone market (~90%). Affordable Android phones from Tecno, Infinix, Itel are very popular."
        return "A computer is an electronic device that processes data according to instructions (programs).\n\n💻 **Components:**\n- **CPU** (Processor): the brain - executes instructions\n- **RAM** (Memory): temporary working space\n- **Storage** (HDD/SSD): permanent data storage\n- **GPU**: handles graphics\n- **Motherboard**: connects everything\n\n**Software types:**\n- Operating System: Windows, macOS, Linux, Android\n- Applications: Chrome, Word, WhatsApp\n- Programming languages: Python, JavaScript, Java\n\nModern smartphones are more powerful than the computers that sent Apollo 11 to the moon in 1969!"
    
    # === CULTURE & SOCIETY ===
    if re.search(r'\b(culture|tradition|custom|festival|music|art|food.*nigeria|nigerian.*food|jollof|egusi|suya|pounded|eba|fufu)\b', t):
        return "Nigerian culture is rich, diverse and vibrant!\n\n🎵 **Music:** Afrobeats is Nigeria's biggest cultural export. Artists like Burna Boy, Wizkid, Davido, Tiwa Savage, Asake have global audiences. Fela Kuti pioneered Afrobeats in the 1970s.\n\n🍛 **Food:** Jollof rice (Nigeria vs Ghana debate!), Egusi soup, Pounded yam, Eba, Suya, Moi Moi, Akara, Puff Puff, Chin Chin. Nigerian cuisine uses rich spices, palm oil, and crayfish.\n\n🎭 **Festivals:** Eyo (Lagos), Durbar (Kano), Osun-Osogbo, Argungu Fishing Festival, New Yam Festival\n\n👗 **Fashion:** Ankara, Aso-ebi, Agbada, Kaftan — Nigerian fashion is globally influential.\n\n500+ ethnic groups, 500+ languages — Nigeria is extraordinary!"
    
    # === SPORTS ===
    if re.search(r'\b(football|soccer|basketball|sport|athlete|world cup|champion|league|super eagles|nba|fifa|olympics|medal)\b', t):
        return "Sports knowledge!\n\n⚽ **Nigerian football:**\n- Super Eagles (men's national team) - 3x Africa Cup of Nations winners (1980, 1994, 2013)\n- Super Falcons (women's team) - 11x Africa Cup of Nations winners!\n- Premier League Nigerian stars: history includes Jay-Jay Okocha, Nwankwo Kanu, John Obi Mikel, Victor Moses\n- Current stars: Victor Osimhen (Napoli), Ademola Lookman (Atalanta)\n\n🏀 **Basketball:** Nigeria's 3x3 team made history. NBA Nigerians: Precious Achiuwa, KJ Martin\n\n🏅 **Olympics:** Nigeria has won medals in athletics, boxing, football\n\nAsk about any specific sport or athlete!"
    
    # === BIOLOGY specific ===  
    if re.search(r'\b(osmosis|diffusion|mitosis|photosynthesis|respiration|ecosystem|food chain|habitat|adaptation|reproduction|cell membrane|nucleus|organ|tissue)\b', t):
        if 'osmosis' in t: return "Osmosis is the movement of water molecules through a semi-permeable membrane from an area of **low solute concentration** to **high solute concentration**.\n\n🔬 **Simply:** water moves from where it is plentiful to where it is less plentiful, until balanced.\n\nExamples:\n- Roots absorbing water from soil\n- Red blood cells shrinking in salty water\n- Skin wrinkling in a bath\n\n**Practical use:** Salt preservation of food works because osmosis draws water out of bacteria, killing them."
        if 'respiration' in t: return "Cellular respiration is how cells release energy from glucose.\n\n**Aerobic respiration (with oxygen):**\nGlucose + Oxygen → Carbon dioxide + Water + **Energy (ATP)**\n\n**Anaerobic respiration (without oxygen):**\nGlucose → Lactic acid + **small amount of Energy**\n(This causes muscle cramps during intense exercise!)\n\nThis process happens in the mitochondria (the 'powerhouse of the cell'). Every cell in your body — and every living organism — uses cellular respiration to stay alive."
        return "Here is a biology answer for '{}':\n\nBiology covers all living systems. The topic '{}' relates to how living organisms function.\n\nKey biology principles:\n- Cell theory: all life is made of cells\n- Evolution: life adapts over time\n- Genetics: traits passed through DNA\n- Homeostasis: maintaining balance\n\nCould you ask a more specific question? For example: 'What is osmosis?' or 'Explain the cell cycle.' I can give a detailed answer!".format(topic, topic)
    
    # === ENVIRONMENT specific ===
    if re.search(r'\b(deforestation|desertification|erosion|flooding|ozone|acid rain|species extinction|biodiversity|ecosystem|conservation|recycling|waste)\b', t):
        return "Environmental issues are critical, especially for Nigeria.\n\n🌱 **Key challenges in Nigeria:**\n- **Desertification** in the north: Lake Chad has shrunk 90% since 1960\n- **Oil spills** in Niger Delta: severely damaged ecosystems\n- **Flooding**: Lagos, Kogi, Anambra face annual flooding\n- **Deforestation**: losing forest cover to farming and logging\n- **Erosion**: South-east Nigeria has severe gully erosion\n\n♻️ **Solutions:**\n- Renewable energy (Nigeria has excellent solar potential)\n- Reforestation programmes\n- Better waste management\n- Sustainable agriculture\n- Reducing dependence on oil\n\n🌍 Nigeria signed the Paris Agreement committing to reduce emissions 20% by 2030."

    # === GOVERNMENT AND POLITICS ===
    if re.search(r'\b(government|democracy|parliament|president|senator|governor|election|vote|constitution|law|court|justice|police|army|military|federal|state|local government)\b', t):
        return "Nigerian Government structure:\n\n🏛️ **Three tiers:**\n- **Federal** (national): President, NASS (Senate + House of Reps), Supreme Court\n- **State** (36 states): Governor, State Assembly, State High Court\n- **Local Government** (774 LGAs): Chairman, Councillors\n\n⚖️ **Three arms:**\n- **Executive** (President/Governor): implements laws\n- **Legislative** (NASS/State Assembly): makes laws\n- **Judiciary** (Courts): interprets laws\n\n🗳️ **Elections:** INEC (Independent National Electoral Commission) conducts elections every 4 years. Presidential, Governorship, and Legislative elections.\n\n📜 **Constitution:** The 1999 Constitution (as amended) is the supreme law of Nigeria."
    
    # ===== DIFFERENCE/COMPARISON QUESTIONS =====
    import re as re_d
    diff_match = re_d.search(r'difference between (.+?) and (.+?)(?:\?|$)', t)
    if diff_match:
        a, b = diff_match.group(1).strip(), diff_match.group(2).strip()
        # Handle specific known comparisons
        if ('air' in a and 'oxygen' in b) or ('oxygen' in a and 'air' in b):
            return "Air vs Oxygen:\n\n🌬️ **Air** is a mixture of gases: 78% Nitrogen, 21% Oxygen, 1% Argon, 0.04% CO2, and trace gases. Air is what we breathe every day.\n\n💧 **Oxygen (O2)** is a single pure gas — just one of the components of air. Pure oxygen is used in hospitals, welding, and rocket fuel.\n\nKey difference: Air = mixture of many gases. Oxygen = one specific gas that makes up 21% of air.\n\nInteresting: We can survive on pure oxygen short-term, but it is actually toxic at high concentrations for long periods!"
        if ('plant' in a and 'animal' in b) or ('animal' in a and 'plant' in b):
            return "Plants vs Animals:\n\n🌿 **Plants:** Make their own food through photosynthesis, have cell walls, cannot move, have no nervous system, absorb water through roots.\n\n🐾 **Animals:** Cannot make their own food (must eat), no cell walls, can move, have nervous system, breathe oxygen.\n\nBoth are living organisms made of cells with DNA. Plants and animals share a common ancestor from ~1.5 billion years ago."
        if ('acid' in a and 'base' in b) or ('acid' in a and 'alkali' in b):
            return "Acid vs Base (Alkali):\n\n⚗️ **Acid:** pH below 7, tastes sour, turns litmus red. Examples: vinegar, lemon juice, stomach acid, battery acid.\n\n🧪 **Base/Alkali:** pH above 7, feels slippery, turns litmus blue. Examples: soap, baking soda, bleach, toothpaste.\n\n**pH 7 = Neutral** (pure water).\n\nWhen acid and base mix they neutralise each other, forming salt and water. This reaction is used in medicine (antacids neutralise stomach acid)."
        if ('speed' in a and 'velocity' in b) or ('velocity' in a and 'speed' in b):
            return "Speed vs Velocity:\n\n🏃 **Speed** = how fast something moves. It is a scalar quantity (magnitude only).\nFormula: Speed = Distance ÷ Time. Example: 60 km/h\n\n🧭 **Velocity** = speed WITH direction. It is a vector quantity.\nExample: 60 km/h northward\n\nKey difference: A car going around a circular track at constant speed has changing velocity (because direction keeps changing)!"
        if ('mass' in a and 'weight' in b) or ('weight' in a and 'mass' in b):
            return "Mass vs Weight:\n\n⚖️ **Mass** = amount of matter in an object. Measured in kg/g. Does NOT change regardless of location.\n\n🌍 **Weight** = force of gravity on an object. Measured in Newtons. CHANGES with gravity.\n\nExample: A 70kg person on Earth weighs 686 N. On the Moon (1/6 gravity) they still have 70kg MASS but weigh only 114 N.\n\nIn everyday life we use 'weight' to mean mass — but in physics they are different!"
        # Generic comparison
        return "Comparing **{}** and **{}**:\n\nBoth '{}' and '{}' are important concepts. The main differences relate to their definition, properties, and applications.\n\nFor a detailed scientific comparison, could you tell me the context? (e.g., in chemistry, biology, physics, economics?) I can then give you precise differences with examples!".format(a, b, a, b)
    
    # ===== CONVERSATIONAL PHRASES =====
    conv_map = {
        r"let.?s chat|want to chat|wanna chat|come let us talk|let us discuss": "Great! I love conversations. I am here and ready to discuss anything — finance, science, health, relationships, technology, history, or just general topics. What is on your mind today?",
        r"i need some enjoyment|entertain me|i.?m bored|nothing to do|cheer me up": "Let me entertain you!\n\n😄 **Fun facts:**\n- Nigeria has more universities than any other African country\n- Snails can sleep for 3 years\n- Honey never expires — edible honey found in 3,000-year-old Egyptian tombs\n- A group of flamingos is called a 'flamboyance'\n- The shortest war in history lasted 38-45 minutes (Anglo-Zanzibar War, 1896)\n\n💰 **Money fun:** If you save N200/day starting today, in 10 years you will have N730,000 before interest! Small steps, big results.\n\nWant more fun facts or shall we play a quiz?",
        r"i.?m hungry|i need food|i want to eat|what to eat|i.?m thirsty": "I cannot feed you physically but I can help you eat cheaper! 😄\n\nBudget meal ideas for Nigerians:\n🍳 Eggs and bread (N200-300) — protein-rich\n🫘 Rice and beans (N300-400) — filling and nutritious\n🌽 Corn and pear/groundnut (N150-200) — healthy snack\n🥜 Indomie with egg (N250) — quick and cheap\n\nTip: Cooking at home saves N1,500-3,000 per month versus buying food outside. Your wallet will thank you!",
        r"i.?m tired|i need rest|i.?m exhausted|i.?m sleepy|i need sleep": "Rest is essential! Your body repairs itself during sleep. Tips:\n😴 Get 7-8 hours of sleep per night\n📵 Put phone away 30 minutes before bed (blue light disrupts sleep)\n🌙 Sleep in a cool, dark room\n☕ Avoid caffeine (tea, coffee) after 3pm\n\nInteresting fact: Sleep deprivation costs Nigeria billions in lost productivity annually. Well-rested workers are 20% more productive. Rest is literally good for your finances too!",
        r"i.?m sick|i don.?t feel well|i have fever|i have headache|i have pain": "I am sorry to hear you are not feeling well! Important: I am not a doctor — please see a healthcare professional for proper diagnosis.\n\n🏥 **General first aid tips:**\n- Fever: Rest, drink plenty of water, take paracetamol if above 38°C\n- Headache: Rest, hydrate, avoid bright screens, paracetamol\n- Malaria symptoms (fever + chills): Go to a pharmacy or clinic IMMEDIATELY — do not delay\n\nNearest help: Government hospitals, private clinics, pharmacies. Health is more important than any financial concern!",
        r"good morning|good morning tanadi": "Good morning! I hope you slept well and you are ready for a productive day. Remember: every great day starts with a positive mindset and a clear plan. What would you like to discuss today — or shall we start with a quick savings check?",
        r"good night|good night tanadi": "Good night! Rest well. While you sleep, let your savings work for you — money in Piggyvest earns interest even overnight. Sweet dreams, and come back tomorrow with any questions!",
    }
    
    for pattern, response in conv_map.items():
        if re_d.search(pattern, t):
            return response
    
    # ===== HAUSA PHRASES =====
    hausa_map = {
        r"ya kake|yaya kake|ina kwana|lafiya lau|ya yini|sannu da zuwa|yaya aiki": "Lafiya! Ni Tanadi ne. Zan iya taimaka maka da duk wani tambaya — kudi, lafiya, ilimi, kimiyya, ko duk wani batu. Mene ne kake son sani yau?",
        r"ina so|na so|kai tsaye|don allah|yaushe|wanene|menene|yaya": "Sannu! Zan taimaka maka. Tambaya ta iya zama game da kudi, lafiya, ko wani batu. Yi min cikakken tambaya don in iya ba da amsa madaidaiciya!",
    }
    for pattern, response in hausa_map.items():
        if re_d.search(pattern, t):
            return response
    
    # ===== DEFINE/SECURITY/GENERAL WORD DEFINITIONS =====
    define_map = {
        'security': "Security means protection from harm, danger, or loss.\n\n🛡️ **Types of security:**\n- **Personal security**: keeping yourself physically safe\n- **Financial security**: having enough money saved (emergency fund, stable income)\n- **Cybersecurity**: protecting computer systems and data\n- **National security**: protecting a country from threats\n- **Food security**: having reliable access to sufficient food\n\nIn finance: Financial security means having savings, insurance, diversified income, and low debt. The goal of Tanadi is to help you achieve financial security!",
        'freedom': "Freedom is the power or right to act, speak, and think without external restraint.\n\n🕊️ **Types of freedom:**\n- Political freedom: right to vote, free speech, free press\n- Economic freedom: ability to work and trade freely\n- Personal freedom: choice of lifestyle, religion, relationships\n- Financial freedom: having enough passive income to cover living expenses\n\nNigeria's freedom: Gained independence (political freedom) on October 1, 1960. Financial freedom is the ultimate goal — and it starts with saving consistently!",
        'success': "Success is achieving your goals and living a fulfilling life.\n\n🌟 **Keys to success:**\n1. Clear goals — know exactly what you want\n2. Consistent action — do something toward your goal every day\n3. Resilience — bounce back from failures\n4. Continuous learning — never stop growing\n5. Good relationships — surround yourself with positive people\n6. Financial discipline — save and invest regularly\n\nIn Nigeria: Education, hard work, networking, and financial discipline are the proven paths to success. What specific area of success are you working on?",
        'happiness': "Happiness is a state of wellbeing and positive emotions. Research shows it comes from:\n\n😊 **What truly brings happiness:**\n- Strong relationships (family, friends, community)\n- Sense of purpose and meaning\n- Good health (physical and mental)\n- Financial security (not wealth, but security)\n- Achieving personal goals\n- Gratitude and mindfulness\n\nInteresting: Research shows that beyond meeting basic needs, more money has diminishing returns on happiness. Strong social bonds are the biggest predictor of happiness worldwide.",
        'knowledge': "Knowledge is information, understanding, and skills acquired through experience, education, or study.\n\n📚 **Types:**\n- Factual knowledge: knowing facts and information\n- Procedural knowledge: knowing how to do things\n- Conceptual knowledge: understanding ideas and relationships\n- Metacognitive knowledge: knowing how you learn best\n\nSocrates said: 'The only true wisdom is knowing that you know nothing' — stay humble and keep learning. Knowledge is the one investment that can never be taken from you!",
        'intelligence': "Intelligence is the ability to learn, reason, solve problems, and adapt to new situations.\n\n🧠 **Types (Howard Gardner's Theory):**\n- Linguistic (language skills)\n- Logical-mathematical\n- Spatial (visual thinking)\n- Musical\n- Bodily-kinesthetic\n- Interpersonal (social skills)\n- Intrapersonal (self-awareness)\n- Naturalist (understanding nature)\n\nIQ measures one type. Emotional Intelligence (EQ) — managing emotions and relationships — is equally important for life success. AI like me is a form of machine intelligence!",
        'time': "Time is the indefinite continued progress of existence and events.\n\n⏰ **Key facts:**\n- Time moves at the same rate for everyone (1 second per second)\n- Einstein showed time moves slightly slower at higher speeds (time dilation)\n- The universe is approximately 13.8 billion years old\n\n💰 **Time and money:** Compound interest makes time the most powerful force in finance! N10,000 saved monthly at 15% annually becomes N3.5 million in 10 years vs only N1.2 million with no interest. Start saving NOW — time is your greatest asset!",
    }
    
    for word, definition in define_map.items():
        if word in t:
            return definition
    
    # ===== TRULY UNKNOWN - BUT ANSWER INTELLIGENTLY =====
    # Don't ask for clarification - give the best possible answer
    topic_clean = (topic or original_msg or 'that topic').strip()[:60]
    o_clean = (original_msg or '').strip()
    
    # If it looks like a greeting/feeling expression
    if re_d.search(r'^(i need|i want|i feel|help me|can you|please|okay|alright|sure|yes|no|maybe)', t):
        if 'need' in t or 'want' in t:
            need = re_d.sub(r'^(i need|i want)\s*', '', t).strip()
            return "I understand you need {}. I am here to help!\n\nI can assist with:\n💰 Financial advice and savings analysis\n🧠 Knowledge on any topic (science, health, history, tech)\n💬 Conversation and emotional support\n🇳🇬 Nigerian-specific information\n\nCould you tell me more specifically what you are looking for? I am ready to give you a full, helpful response right away!".format(need or 'assistance')
    
    # If message has 1-3 words, treat as a topic to define
    words = topic_clean.split()
    if 1 <= len(words) <= 3:
        return "Here is what I know about **'{}'**:\n\nThis is a topic I can discuss! For the best answer, could you ask as a full question? Examples:\n- 'What is {}?'\n- 'Explain {} in simple terms'\n- 'How does {} work?'\n- 'Tell me about {}'\n\nI am ready to give a complete answer immediately! I cover science, health, technology, history, finance, relationships, and much more.".format(topic_clean, topic_clean, topic_clean, topic_clean, topic_clean)
    
    # Longer message - give a genuinely helpful response
    return "Thank you for your message! I want to give you the most helpful response possible.\n\nRegarding '{}': I am ready to discuss this in detail. I have knowledge covering science, technology, health, medicine, finance, Nigerian culture, world history, relationships, education, grammar, mathematics, environment, government, sports, religion, and much more.\n\nPlease rephrase as a direct question and I will answer immediately with full detail. For example: 'What is...?', 'How does...?', 'Explain...', or 'Tell me about...'".format(topic_clean)


def smart_reply(msg, history=None):
    """Hyper-intelligent built-in AI - answers virtually anything like ChatGPT."""
    import re, random
    if not msg or not msg.strip():
        return "Hello! I'm Tanadi, your AI assistant. Ask me anything — savings, money, life advice, science, history, health, relationships — I'm here to help in any language!"
    m = msg.lower().strip()
    h = history or []

    # ===== EMOTIONAL / SOCIAL =====
    if re.search(r'\b(i love you|i like you|love you|i adore you)\b', m):
        return "Aww, I love you too! You are amazing for working on your finances. Now let's make sure your money loves you back! What can I help you with today?"
    if re.search(r'\b(do you love me|do you like me)\b', m):
        return "Of course I do! I care about every user I talk to. You matter, and so does your financial future. What's on your mind today?"
    if re.search(r'\b(hi|hello|hey|good morning|good afternoon|good evening|howdy|yo|sup|hy|hii|helo)\b', m):
        greetings = [
            "Hello! I'm Tanadi, your AI assistant. I can help with savings, money, health, science, general knowledge — anything! What would you like to talk about?",
            "Hi there! Great to see you! Ask me anything — I'm like ChatGPT but built for Nigerians. What's on your mind?",
            "Hey! Welcome to Tanadi! I can answer questions on any topic or help you save more money. What would you like to know?"
        ]
        return random.choice(greetings)
    if re.search(r'\b(how are you|how r u|how are u|hows it going|you okay|you good|how do you do)\b', m):
        return "I'm doing fantastic, thank you for asking! I'm energised and ready to help you with anything — money, life, general knowledge, whatever you need. How are YOU doing today?"
    if re.search(r'\b(thank|thanks|thank you|thx|appreciate|grateful|merci|gracias|danke|asante)\b', m):
        return "You're very welcome! I'm always here for you. Feel free to ask me anything anytime. Keep saving and keep growing!"
    if re.search(r'\b(bye|goodbye|see you|later|take care|ciao|au revoir|hasta luego)\b', m):
        return "Goodbye! Remember — every naira saved today builds your tomorrow. Come back anytime you need help. Take care!"
    if re.search(r'\b(sorry|apologize|my bad|i made a mistake|forgive)\b', m):
        return "No need to apologise at all! Everyone makes mistakes — that's how we learn. Now, how can I help you today?"
    if re.search(r'\b(i.?m sad|i am sad|feeling sad|feeling down|depressed|unhappy|not happy|i.?m crying|i feel bad)\b', m):
        return "I'm truly sorry you're feeling this way. It's okay to have hard days — they don't last forever. Remember, you're stronger than you think. Is there anything I can do to help? Sometimes talking about finances and having a plan can reduce stress a lot."
    if re.search(r'\b(i.?m happy|i.?m excited|great news|amazing news|i feel good|i.?m grateful)\b', m):
        return "That's wonderful! I love hearing positive energy! Happiness and good finances go hand in hand. What's the great news? And shall we celebrate by setting a new savings goal?"
    if re.search(r'\b(bored|boring|nothing to do|i.?m bored)\b', m):
        return "Let's fix that! Did you know: the average Nigerian can save N2,000 more per month just by switching to monthly data bundles and cooking at home one extra day per week? Tell me your income and I'll show you hidden savings you didn't know you had!"
    if re.search(r'\b(joke|funny|make me laugh|tell me something funny|humor)\b', m):
        jokes = [
            "Why did the naira go to therapy? Because it had too many cents of self-doubt! 😄 But seriously, a strong savings habit is the best therapy for your finances!",
            "What do you call a Nigerian who saves 30% of income? A future millionaire! 😄 Want to be one? Tell me your income!",
            "Why don't ATMs ever get lonely? Because they always have many friends withdrawing from them! 😄 Make sure you're depositing more than you withdraw!"
        ]
        return random.choice(jokes)
    if re.search(r'\b(who are you|what are you|tell me about yourself|what is tanadi|introduce yourself)\b', m):
        return "I'm Tanadi — an AI savings assistant and general knowledge chatbot built for Nigerians. I can:\n✅ Analyse your income and expenses\n✅ Give savings and budgeting advice\n✅ Answer questions on ANY topic — science, history, health, tech, relationships\n✅ Speak multiple languages including Pidgin, Hausa, Yoruba, Igbo\n✅ Help you link your bank and grow your vault\n\nThink of me as ChatGPT + financial coach in one app!"

    # ===== SCIENCE & NATURE =====
    if re.search(r'\b(how does the sun work|what is the sun|how big is the sun)\b', m):
        return "The Sun is a giant ball of hot plasma powered by nuclear fusion — hydrogen atoms fuse together to form helium, releasing enormous energy. It's about 1.4 million km wide (109 times Earth's diameter) and sits 150 million km away. Without it, all life on Earth would end within weeks."
    if re.search(r'\b(how does the moon|what is the moon|why does the moon)\b', m):
        return "The Moon is Earth's natural satellite, formed about 4.5 billion years ago. It has no atmosphere and its gravity is 1/6 of Earth's. The Moon controls Earth's tides and stabilises our planet's axial tilt, making stable seasons possible. One side always faces Earth due to tidal locking."
    if re.search(r'\b(how does rain|why does it rain|water cycle|evaporation)\b', m):
        return "Rain forms through the water cycle: the sun heats water in oceans/rivers causing evaporation → water vapour rises and cools → condenses into clouds → droplets grow heavy and fall as rain. In Nigeria, the rainy season (April-October in the south) is crucial for farming and water supply."
    if re.search(r'\b(how does electricity|how does power|how is electricity made)\b', m):
        return "Electricity is generated by moving magnets near coils of wire (electromagnetic induction). Power plants use turbines spun by steam (from burning gas/coal or nuclear heat), water (hydroelectric), or wind. In Nigeria, the Kainji Dam on the Niger River generates hydroelectric power. The electricity flows through the national grid to your home."
    if re.search(r'\b(climate change|global warming|greenhouse|carbon dioxide)\b', m):
        return "Climate change is the long-term warming of Earth caused mainly by humans burning fossil fuels (coal, oil, gas), which releases CO2 into the atmosphere. This traps heat (greenhouse effect). Effects include: rising sea levels, extreme weather, droughts, floods. Nigeria faces serious risks including desertification in the north and coastal flooding in Lagos/Delta regions."
    if re.search(r'\b(how does the human body|how does the brain|how does the heart|how does digestion)\b', m):
        return "The human body is extraordinarily complex! The heart pumps blood 100,000 times/day. The brain has ~86 billion neurons. The gut has its own nervous system (the 'second brain'). The liver performs 500+ functions. You replace most of your cells every 7-10 years. Is there a specific body system you'd like to know more about?"
    if re.search(r'\b(what is dna|how does dna work|genetics|gene|chromosome)\b', m):
        return "DNA (deoxyribonucleic acid) is the molecule that carries your genetic instructions. It's shaped like a double helix — two strands twisted together. Every cell in your body contains about 3 billion base pairs of DNA. Your DNA is 99.9% identical to every other human, and about 98.7% similar to chimpanzee DNA. Genes are segments of DNA that code for specific traits."
    if re.search(r'\b(what is ai|artificial intelligence|machine learning|how does ai work)\b', m):
        return "Artificial Intelligence (AI) refers to computer systems that can perform tasks that normally require human intelligence — like understanding language, recognising images, or making decisions. I'm an AI! I work by pattern matching across millions of examples. Modern AI like ChatGPT uses 'large language models' trained on billions of words from the internet."

    # ===== HEALTH & MEDICINE =====
    if re.search(r'\b(how to lose weight|weight loss|diet|calories|fat|obesity)\b', m):
        return "Safe weight loss fundamentals:\n1. **Caloric deficit**: eat ~500 fewer calories/day than you burn\n2. **Protein**: eat eggs, beans, fish, chicken to stay full longer\n3. **Reduce sugar**: stop fizzy drinks, reduce rice portions\n4. **Exercise**: 30 min walking daily is enough to start\n5. **Sleep**: poor sleep increases hunger hormones\n\nFor Nigerians: swap white rice for brown rice/beans, eat more vegetables, reduce eba/pounded yam portions. Lose 0.5-1kg/week safely."
    if re.search(r'\b(high blood pressure|hypertension|blood pressure)\b', m):
        return "High blood pressure (hypertension) is very common in Nigeria — affecting about 30% of adults. It's called the 'silent killer' because it has no symptoms. Management:\n- Reduce salt (stop adding extra salt, limit stock cubes)\n- Exercise regularly\n- Reduce stress\n- Reduce alcohol\n- Take medication if prescribed\n- Check BP regularly at pharmacy\n\nNormal BP: below 120/80 mmHg. See a doctor if consistently above 140/90."
    if re.search(r'\b(diabetes|blood sugar|insulin|glucose)\b', m):
        return "Diabetes is when your body can't properly regulate blood sugar (glucose). Type 2 diabetes (most common) is often linked to diet and lifestyle. Signs: frequent urination, excessive thirst, blurry vision, slow healing. Management: reduce sugar and refined carbs, exercise, medication if prescribed. Many Nigerians unknowingly have pre-diabetes. A simple fasting blood glucose test at any lab can check."
    if re.search(r'\b(malaria|fever|temperature|paracetamol|artemether)\b', m):
        return "Malaria is the most common illness in Nigeria. Symptoms: fever, chills, headache, body pain, vomiting. Treatment: Artemether-Lumefantrine (Coartem) is the standard first-line treatment. Prevention: sleep under treated mosquito nets, use insect repellent, eliminate standing water. Seek medical care promptly — malaria can become severe quickly, especially in children."
    if re.search(r'\b(stress|anxiety|mental health|depression|panic attack)\b', m):
        return "Mental health matters deeply. Signs of stress/anxiety: constant worry, trouble sleeping, irritability, fast heartbeat. Ways to help:\n- Talk to someone you trust\n- Exercise (even walking reduces cortisol)\n- Practice deep breathing: inhale 4 seconds, hold 4, exhale 4\n- Limit news and social media\n- Prayer/meditation/mindfulness\n- In Nigeria: NIMH (Neuropsychiatric Hospital, Aro) provides mental health services\n\nYou are not alone. It's okay to seek help."

    # ===== TECHNOLOGY =====
    if re.search(r'\b(what is internet|how does internet work|wifi|broadband)\b', m):
        return "The internet is a global network of computers connected together. When you load a webpage, your device sends a request through your WiFi/mobile data → to your ISP (MTN, Airtel, Glo) → through undersea cables → to a server somewhere in the world → which sends back the page data. In Nigeria, most internet access is through mobile data (4G/5G). MTN and Airtel have the best coverage nationally."
    if re.search(r'\b(what is blockchain|what is bitcoin|how does crypto work|ethereum)\b', m):
        return "Blockchain is a digital ledger where transactions are recorded in 'blocks' chained together — making records permanent and nearly impossible to alter. Bitcoin was the first cryptocurrency, created in 2009. It uses blockchain to enable peer-to-peer payments without a bank.\n\n⚠️ **Nigeria warning**: Crypto is highly volatile. The SEC Nigeria has regulations around it. NEVER invest money you can't afford to lose 100%. Build your emergency fund first."
    if re.search(r'\b(how to code|learn programming|python|javascript|coding|software)\b', m):
        return "Great choice to learn coding! Best free resources:\n- **Python**: python.org, freeCodeCamp.org (best for beginners)\n- **Web dev**: HTML/CSS/JS on freeCodeCamp, The Odin Project\n- **YouTube**: Traversy Media, Fireship, CS50 Harvard (free!)\n\nFor Nigerians: Semicolon Africa, Decagon, AltSchool offer local bootcamps. coding skill can 5-10x your income potential. Start with Python — it's the most learnable first language."
    if re.search(r'\b(what is 5g|5g network|4g|internet speed)\b', m):
        return "5G is the 5th generation of mobile network technology. Compared to 4G: 10-100x faster speeds, much lower latency. In Nigeria, MTN and Mafab Communications have 5G licences. 5G enables smart cities, autonomous vehicles, and IoT. However, 4G is still the standard for most Nigerians and works well for all current needs."

    # ===== HISTORY & CULTURE =====
    if re.search(r'\b(history of nigeria|nigeria history|when was nigeria founded)\b', m):
        return "Nigeria's key historical moments:\n- 1914: Lord Lugard amalgamated Northern and Southern Protectorates into 'Nigeria'\n- 1960: Independence from Britain on October 1st\n- 1967-1970: Civil War (Biafra conflict)\n- 1999: Return to civilian democracy after military rule\n- 2006: Nigeria paid off its entire $30bn foreign debt\n\nNigeria has 36 states, 774 LGAs, and 500+ ethnic groups. It's the most populous African nation (~220 million people) and largest economy in Africa."
    if re.search(r'\b(who is the president of nigeria|nigerian president|tinubu|president of nigeria)\b', m):
        return "As of my knowledge, Bola Ahmed Tinubu is the President of Nigeria, inaugurated on May 29, 2023. He served as Lagos State Governor from 1999-2007 and is widely credited with transforming Lagos's economy. His administration has focused on subsidy removal, naira reforms, and infrastructure. For the very latest news, please check a Nigerian news source like Punch, Vanguard, or Channels TV."
    if re.search(r'\b(africa|african|continent|most populous|richest country africa)\b', m):
        return "Africa facts:\n- 54 countries, 1.4 billion+ people\n- Nigeria = most populous (220m+) and largest economy\n- Egypt, Ethiopia, DRC = also very large by population\n- Most spoken languages: Arabic, Swahili, Hausa, Amharic\n- Youngest continent by median age (~19 years)\n- Fastest growing mobile market in the world\n- Africa is projected to have 2.5 billion people by 2050"

    # ===== FINANCE & SAVINGS =====
    income_keywords = ['earn','income','salary','made','got','receive','monthly']
    spend_keywords = ['spend','spent','expenses','cost','pay','use']
    nums = re.findall(r'n?\s*(\d[\d,]*)', m)
    amounts = []
    try: amounts = [int(n.replace(',','')) for n in nums if int(n.replace(',','')) > 100]
    except: pass
    if amounts and len(amounts) >= 2 and (any(w in m for w in income_keywords) or any(w in m for w in spend_keywords)):
        inc = amounts[0]
        spent = sum(amounts[1:])
        saved = inc - spent
        rate = round(saved/inc*100, 1) if inc > 0 else 0
        if rate >= 20: grade,tip = "Excellent 🌟","You're in the top 10% of savers in Nigeria! Consider investing surplus in Treasury Bills or Piggyvest."
        elif rate >= 10: grade,tip = "Good 👍","Above average! Push to 20% by cutting one expense category by 20% this month."
        elif rate >= 5: grade,tip = "Fair 📈","You're saving something — great start! Try the Pay Yourself First method to boost this."
        elif rate > 0: grade,tip = "Needs Work ⚠️","Try saving FIRST before spending — even N200/day adds up to N6,000/month."
        else: grade,tip = "Critical 🚨","You spent more than you earned! Let's find where the leaks are."
        lines = [
            "Here's your savings analysis:",
            "",
            f"SCORE: {grade}",
            f"YOUR SAVINGS: N{max(0,saved):,} ({max(0,rate)}%)",
            f"RECOMMENDED: N{int(inc*0.2):,}/month (20% rule)",
            f"TIP: {tip}",
            "",
            "Go to the Budget tab for a full detailed breakdown with ML predictions!"
        ]
        return "\n".join(lines)

    if re.search(r'\b(how much to save|how much should i save|savings rate|what percentage)\b', m):
        return "The golden rule: **save 10-20% of your income.**\n\nExamples:\n- N5,000/month → save N500-1,000\n- N7,000/month → save N700-1,400\n- N10,000/month → save N1,000-2,000\n\nStart with 5% if 10% feels hard. Increase by 1% every month. Even N200/week = N10,400/year!"
    if re.search(r'\b(emergency fund|emergency savings|safety net)\b', m):
        return "An emergency fund = 3-6 months of expenses saved separately. For N5,000/month expenses → save N15,000-30,000. Keep it in a high-interest account (Kuda, Piggyvest) so it earns interest. This protects you from job loss, medical bills, or unexpected costs without going into debt."
    if re.search(r'\b(debt|loan|borrow|owe|owing|carbon loan|branch loan|fairmoney)\b', m):
        return "Debt management steps:\n1. Stop borrowing immediately — no new debts\n2. List all debts with amounts and interest rates\n3. Pay highest-interest debt first (fintech loans often 10-30%/month!)\n4. Always pay minimums on all debts\n5. Negotiate — lenders often accept reduced amounts\n6. While clearing debt, still save N500/month minimum for emergencies\n\n⚠️ FairMoney, Carbon, Branch charge very high monthly interest — avoid if possible."
    if re.search(r'\b(invest|investment|where to invest|stock market|treasury bill)\b', m):
        return "Best investments for Nigerians (low to high risk):\n\n🟢 **Low risk:**\n- Treasury Bills (CBN): ~18-21% p.a., very safe\n- Fixed Deposits (banks): 10-15% p.a.\n- Piggyvest/Cowrywise savings: 10-13% p.a.\n\n🟡 **Medium risk:**\n- Nigerian Stock Exchange (Stanbic, Zenith, MTNN shares)\n- Agriculture (ThriveAgric, Farmcrowdy): 15-25% returns\n\n🔴 **High risk:**\n- Cryptocurrency (Bitcoin, Ethereum)\n- Forex trading\n\nStart low risk, build capital, then diversify!"
    if re.search(r'\b(food|eat|meal|market|cook|feeding|groceries)\b', m):
        return "Food savings (Nigerian context):\n🛒 Buy at Balogun, Mile 12, Bodija market — not supermarket (30-50% cheaper)\n🍳 Cook at home 5x/week (saves N2,000-4,000/month vs buying food)\n📋 Plan meals weekly before shopping\n🛍️ Buy in bulk: 10kg rice, 5L oil, etc.\n🚫 Limit fast food to once per week max\n\nAverage Nigerian spends 32% of income on food. Cutting 20% = significant savings!"
    if re.search(r'\b(transport|bus|keke|okada|uber|bolt|fuel|fare|commute|danfo)\b', m):
        return "Transport savings:\n🚌 Danfo/BRT over Uber/Bolt — can be 5-10x cheaper\n🛺 Keke over cab for short trips\n🤝 Carpool with colleagues going same direction\n🚶 Walk trips under 15 minutes\n📱 Use Bolt/Uber pool option — 40% cheaper\n\nMost Nigerians can save N500-2,000/month on transport with small habit changes."
    if re.search(r'\b(data|airtime|mtn|glo|airtel|9mobile|recharge|bundle)\b', m):
        return "Data savings:\n📦 Monthly bundles > weekly > daily (much cheaper per GB)\n📶 MTN 10GB monthly ~N2,000 vs N3,500 in weekly bundles\n📲 Use WiFi whenever available (offices, restaurants, home)\n⬇️ Download content offline on WiFi (Netflix, YouTube)\n📵 Turn off background data for unused apps\n\nCompare prices monthly — networks change bundles often. Most people waste N300-600/month!"

    # ===== LANGUAGES =====
    hausa_patterns = ['sannu', 'ina kwana', 'lafiya', 'nagode', 'yaya', 'kudi', 'adana', 'kana', 'yana']
    yoruba_patterns = ['bawo', 'e kaaro', 'e kaasan', 'jowo', 'ese', 'owo', 'dara', 'pele', 'ekabo']
    igbo_patterns = ['kedu', 'ndewo', 'daalu', 'ego', 'udo', 'ezigbo', 'gwa m', 'i na']
    pidgin_patterns = ['abeg', 'na wa', 'wetin', 'ehen', 'shey', 'wahala', 'dey', 'wey', 'comot', 'oya', 'na im', 'e don', 'una']
    french_patterns = ['bonjour', 'merci', 'comment', 'argent', 'salut', 'bonsoir', 'comment allez', 'je veux', 'aide moi']

    if any(w in m for w in hausa_patterns):
        return "Sannu! Ni Tanadi ne, mataimakinka na kudi da ilimi. Zan iya taimaka maka:\n- Ka gaya min kudinku na wata — zan bincika ajiyar ku\n- Tambaya game da yadda ake adana kudi\n- Ko tambaya game da kowane batu a duniya\n\nYaya kudin ku ke tafiya wannan watan?"
    if any(w in m for w in yoruba_patterns):
        return "E kaabo! Emi ni Tanadi, oluranlowo owo ati imo re. Mo le ran e lowo:\n- So fun mi owo ti o n gba lowo si - emi o se itupalẹ afipamo\n- Beere nipa bi a se le fipamo owo\n- Tabi ibeere eyikeyi nipa igbesi aye\n\nEla owo re ati inawo re fun mi!"
    if any(w in m for w in igbo_patterns):
        return "Ndewo! Abu m Tanadi, onye nkuzi ego gị na ihe ọ bụla. Nwere ike inyere gị aka:\n- Kọọ m ego gị kwa ọnwa — a ga m atụle ego i letaba\n- Jụọ ajụjụ gbasara ibi ego\n- Ma ọ bụ ajụjụ ọ bụla n'ụwa\n\nKedu ego i na-enweta kwa ọnwa?"
    if any(w in m for w in pidgin_patterns):
        return "Ehen! Na me be Tanadi — your savings coach and general knowledge bot wey sabi everything! I fit help you:\n🔥 Tell me how much you dey earn — I go analyse your money situation\n💡 Ask me anything — money, health, science, relationship — anything!\n🏦 Help you link your bank account\n\nAbeg tell me your monthly income so I go show you how to save better!"
    if any(w in m for w in french_patterns):
        return "Bonjour! Je suis Tanadi, votre assistant financier et général. Je peux vous aider avec:\n💰 Analyser votre budget et vos économies\n📚 Répondre à toutes vos questions\n🏦 Conseils bancaires nigérians\n\nCombien gagnez-vous par mois? Je peux vous montrer comment économiser plus!"

    # ===== RELATIONSHIPS & LIFE =====
    if re.search(r'\b(relationship|boyfriend|girlfriend|marriage|husband|wife|partner|love life|dating)\b', m):
        return "Love and money are deeply connected! Financial stress is the #1 cause of relationship breakdowns in Nigeria. Tips:\n💑 Have honest money conversations early in relationships\n📊 Create shared budgets if living together\n🚫 Never keep major financial secrets from your partner\n💪 Build individual emergency funds before combining finances\n🎯 Set shared savings goals (house, wedding, children's education)\n\nA financially stable relationship is a happy relationship!"
    if re.search(r'\b(job|career|salary|promotion|unemployed|work|employment|hustle)\b', m):
        return "Career & income tips for Nigerians:\n📈 Research market rates: LinkedIn, Glassdoor, Jobberman\n💬 Negotiate salary — most people never ask, those who ask get 10-20% more\n🎓 Upskill constantly: Coursera, edX, Udemy (many free courses)\n💼 Side hustle ideas: freelancing, tutoring, mini-importation, food business, digital skills\n🌐 Remote work is growing — Upwork, Fiverr, Toptal for tech/creative skills\n\nAim for multiple income streams — the average millionaire has 7!"
    if re.search(r'\b(school|education|university|study|learn|scholarship|jamb|waec|neco)\b', m):
        return "Education guidance for Nigerians:\n🎓 JAMB/WAEC/NECO: focus on past questions — patterns repeat!\n🏫 Nigerian universities: UNILAG, UI, ABU, OAU, UNIBEN are top-ranked\n💰 Scholarships: check scholarshipportal.com, opportunitiesforafricans.com\n📱 Free learning: Khan Academy, Coursera, YouTube (MIT OpenCourseWare)\n💡 Even while studying, save N200-500/week — compound interest works for you\n\nEducation is the best investment with guaranteed returns!"
    if re.search(r'\b(weather|rain|temperature|forecast|hot|cold|harmattan|rainy season)\b', m):
        return "I don't have real-time weather data, but here's Nigeria's weather pattern:\n☀️ **Dry season**: November-March (North stays drier longer)\n🌧️ **Rainy season**: April-October in South (June-September peak)\n💨 **Harmattan**: December-February — dusty, cold nights, dry skin\n🌡️ Average temperatures: 25-35°C in most of Nigeria year-round\n\nFor today's exact forecast: check Google Weather, AccuWeather, or the NiMet app (Nigerian Meteorological Agency)."

    # ===== LOVE & RELATIONSHIPS (specific) =====
    if re.search(r'\b(what is love|about love|define love|explain love|meaning of love|information about love|types of love)\b', m):
        return "Love is a deep emotional bond between people. Psychologists identify several types:\n\n❤️ **Romantic love** - passionate attraction between partners\n👨‍👩‍👧 **Familial love** - the bond between family members\n👫 **Friendship love** - deep care for close friends\n💚 **Self-love** - healthy respect and appreciation for yourself\n♾️ **Unconditional love** - love with no conditions attached\n\nPsychologist Sternberg's Love Triangle: Intimacy (closeness) + Passion (attraction) + Commitment = Complete love.\n\nHealthy love involves mutual respect, trust, honest communication, and support. In Nigerian culture, love also includes family acceptance, shared values, and responsibility."

    # ===== INSURANCE =====
    if re.search(r'\b(what is.*insurance|define.*insurance|insurance mean|life insurance|health insurance|explain.*insurance|about insurance)\b', m):
        if re.search(r'life', m):
            return "Life insurance is a contract where you pay regular premiums, and if you die, the company pays a lump sum (death benefit) to your family.\n\n✅ **Why get it:**\n- Protects your family if you die unexpectedly\n- Covers funeral costs\n- Replaces your income for dependants\n- Pays off debts\n\n🏢 **Nigerian providers:** AIICO Insurance, Leadway Assurance, AXA Mansard, FBN Insurance\n\n💰 **Cost:** From ~N3,000/month for basic cover\n\n📌 **Rule of thumb:** Get coverage worth 10x your annual income"
        if re.search(r'health', m):
            return "Health insurance covers your medical bills. You pay monthly premiums and the insurer covers hospital visits, drugs, and treatments.\n\n🏥 **In Nigeria:**\n- NHIS (National Health Insurance Scheme) = government scheme\n- Private HMOs: Hygeia, Reliance, AXA Mansard Health, Sanlam\n- Cost: N5,000-15,000/month for private HMO\n\n✅ **Benefits:** Reduces out-of-pocket costs by up to 80%\n\nMany employers provide group health insurance. If self-employed, prioritise getting HMO coverage — one hospital admission can wipe out months of savings!"
        return "Insurance is financial protection — you pay regular premiums and the insurer compensates you when something bad happens.\n\n📋 **Main types in Nigeria:**\n1. **Life insurance** - pays family if you die\n2. **Health insurance** - covers medical bills (HMO)\n3. **Car insurance** - legally required, covers accidents\n4. **Home insurance** - protects your property\n5. **Business insurance** - covers business losses\n\n🏢 **Nigerian companies:** AIICO, Leadway, AXA Mansard, Cornerstone, FBN Insurance\n\n⚠️ Only ~1% of Nigerians are insured — one of the lowest rates in the world. Insurance is one of the most underused financial tools!"

    # ===== ECONOMICS =====
    if re.search(r'\b(what is.*economy|define.*economy|what is economics|define economics|gdp|gross domestic|national income|economic)\b', m):
        return "Economics studies how societies produce, distribute, and consume goods and services.\n\n📊 **Key concepts:**\n- **GDP** = total value of goods/services produced in a year. Nigeria's GDP ~$477 billion (largest in Africa)\n- **Inflation** = prices rising over time (Nigeria has faced high inflation recently)\n- **Interest rate** = cost of borrowing money, set by CBN\n- **Exchange rate** = value of naira vs other currencies\n\n📈 **Branches:**\n- Microeconomics = individual/firm decisions\n- Macroeconomics = national/global economy\n\nUnderstanding economics helps you make smarter financial decisions about savings, investments, and spending!"

    # ===== BIOLOGY =====
    if re.search(r'\b(what is biology|define biology|explain biology|what is photosynthesis|how do plants|cell biology|what is a cell)\b', m):
        if re.search(r'photosynthesis', m):
            return "Photosynthesis is the process plants use to make food from sunlight.\n\n🌱 **Formula:** CO₂ + Water + Sunlight → Glucose + Oxygen\n\nChlorophyll (the green pigment in leaves) captures sunlight energy. This energy converts carbon dioxide (from air) and water (from roots) into glucose (sugar) for energy, and releases oxygen as a byproduct.\n\n🌍 **Why it matters:** All food chains start with photosynthesis. It also produces the oxygen we breathe. Without photosynthesis, almost all life on Earth would not exist!"
        return "Biology is the science of life — studying all living organisms from bacteria to blue whales.\n\n🔬 **Main branches:**\n- **Cell biology** - the basic unit of life\n- **Genetics** - DNA and inheritance\n- **Ecology** - organisms and their environment\n- **Zoology** - animals\n- **Botany** - plants\n- **Microbiology** - bacteria, viruses, fungi\n- **Human anatomy** - the human body\n\n💡 **Key facts:** All living things are made of cells. DNA carries genetic instructions. Evolution explains how species developed. Biology underpins medicine, agriculture, and environmental science."

    # ===== CHEMISTRY =====
    if re.search(r'\b(what is chemistry|define chemistry|explain chemistry|atom|molecule|periodic table|chemical reaction|element)\b', m):
        return "Chemistry is the science of matter — what things are made of and how they interact and change.\n\n⚗️ **Key branches:**\n- **Organic chemistry** = carbon compounds (medicines, plastics, food)\n- **Inorganic chemistry** = metals, minerals, salts\n- **Physical chemistry** = energy in reactions\n- **Biochemistry** = chemistry of living things\n\n🔬 **Key concepts:**\n- Atoms are the smallest particles of an element\n- Molecules are atoms bonded together\n- The Periodic Table organises 118 known elements\n- Chemical reactions rearrange atoms to form new substances\n\n🇳🇬 Chemistry in daily Nigerian life: the soap you use, the fuel in cars, the food you digest, and the medicines you take are all chemistry!"

    
    
    # ===== SPECIFIC SCIENCE =====
    if re.search(r'\b(photosynthesis|how do plants make food|chlorophyll)\b', m):
        return "Photosynthesis is how plants make their own food using sunlight.\n\n🌿 **Formula:** CO₂ + Water + Sunlight → Glucose + Oxygen\n\n**Process:** Chlorophyll (green pigment in leaves) captures sunlight. This energy converts CO₂ from air and water from roots into glucose (energy for plant) and releases oxygen as a byproduct.\n\n🌍 **Why it matters:** All food chains start with photosynthesis. It produces the oxygen we breathe. Without it, almost no life on Earth would exist! Plants, algae, and some bacteria can photosynthesize."
    if re.search(r'\b(gravity|newton.*law|force.*mass|how does gravity)\b', m):
        return "Gravity is the force of attraction between any two objects with mass. Newton's Law: F = Gm₁m₂/r². The more massive the object and the closer together, the stronger the gravity. Earth's gravity keeps us on the ground and keeps the Moon in orbit. Einstein's General Relativity showed gravity is actually the curvature of spacetime caused by mass. Without gravity, there would be no planets, no stars, and no universe as we know it!"

        # ===== GENERAL KNOWLEDGE =====
    if re.search(r'\b(what is|what are|how does|how do|explain|tell me about|define|meaning of)\b', m):
        if re.search(r'\b(inflation|price rise|cost of living)\b', m):
            return "Inflation is when prices rise over time, reducing what your money can buy. If inflation is 25% per year, N10,000 today buys what N8,000 bought last year. Nigeria has faced high inflation recently. To protect savings: keep money in high-interest accounts (>20% p.a.), invest in real assets (land, gold), or use dollar-backed savings to preserve value."
        if re.search(r'\b(interest rate|apr|apy|compound interest)\b', m):
            return "Interest rate = the cost of borrowing money OR the reward for saving. Compound interest means you earn interest ON your interest — it's the most powerful force in finance!\n\nExample: Save N10,000 at 15% p.a. compounded monthly:\n- Year 1: N11,500\n- Year 5: N20,100\n- Year 10: N40,450\n\nStart saving early — time is your biggest asset!"
        if re.search(r'\b(gravity|newton|physics|force|energy|quantum)\b', m):
            return "Physics is fascinating! Gravity is the force of attraction between masses — described by Newton's Law (F=Gm1m2/r²). Einstein later showed gravity is actually the curvature of spacetime caused by mass. Quantum physics describes the strange behaviour of particles at atomic scale — where particles can exist in multiple states simultaneously. These two theories (General Relativity and Quantum Mechanics) are the foundations of all modern physics."
        if re.search(r'\b(evolution|darwin|natural selection|species|fossil)\b', m):
            return "Evolution by natural selection (Darwin, 1859): organisms with traits better suited to their environment survive and reproduce more. Over millions of generations, this creates new species. The fossil record, DNA analysis, and direct observation all confirm evolution. Humans and chimpanzees share a common ancestor from ~6-7 million years ago. Every living thing on Earth shares a single common ancestor from ~3.8 billion years ago."
        # Generic what/how/explain fallback - actually answer it!
        topic_raw = m
        for prefix in ['what is','what are','how does','how do','how is','explain','define','tell me about',
                        'what do you know about','describe','meaning of','information about','i need.*about',
                        'about','i want to know about','can you explain']:
            import re as re2
            topic_raw = re2.sub(r'^'+prefix+r'\s*', '', topic_raw).strip()
        topic_raw = topic_raw.strip('?.,! ')
        return smart_answer(topic_raw, msg)

    # ===== CATCHALL — intelligent response to ANY message =====
    # Extract the core topic/intent from any message
    import re as re3
    # Try to identify what they're asking about
    topic_match = re3.search(r'(?:about|know|tell|explain|what|who|how|why|when|where|can|could|is|are|do|does)\s+(\w[\w\s]{2,40})', m)
    if topic_match:
        topic = topic_match.group(1).strip()
        return smart_answer(topic, msg)
    # Pure statement - give helpful response
    return smart_answer(m, msg)




def call_groq(hist, system_prompt):
    """Call Groq API - FREE, runs LLaMA 3.3 70B and Mixtral"""
    try:
        gk = get_groq_key()
        if not gk or len(gk) < 20:
            return None
        messages = [{"role": "system", "content": system_prompt}]
        for h in hist[-10:]:
            role = h.get("role","user")
            if role in ("user","assistant"):
                messages.append({"role": role, "content": str(h.get("content",""))[:1000]})
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {gk}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile", "messages": messages, "max_tokens": 600, "temperature": 0.7},
            timeout=15
        )
        result = r.json()
        reply = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        return reply if reply and len(reply) > 5 else None
    except Exception:
        return None

def call_together(hist, system_prompt):
    """Call Together AI - FREE tier, runs Llama 3.1 8B"""
    try:
        tk = get_together_key()
        if not tk or len(tk) < 20:
            return None
        messages = [{"role": "system", "content": system_prompt}]
        for h in hist[-10:]:
            role = h.get("role","user")
            if role in ("user","assistant"):
                messages.append({"role": role, "content": str(h.get("content",""))[:1000]})
        r = requests.post(
            "https://api.together.xyz/v1/chat/completions",
            headers={"Authorization": f"Bearer {tk}", "Content-Type": "application/json"},
            json={"model": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo", "messages": messages, "max_tokens": 600, "temperature": 0.7},
            timeout=15
        )
        result = r.json()
        reply = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        return reply if reply and len(reply) > 5 else None
    except Exception:
        return None

def call_gemini(hist, system_prompt):
    """Call Google Gemini - FREE tier, very capable"""
    try:
        gk = get_gemini_key()
        if not gk or len(gk) < 20:
            return None
        # Build conversation
        contents = []
        for h in hist[-10:]:
            role = h.get("role","user")
            content = str(h.get("content",""))[:1000]
            if role == "user":
                contents.append({"role": "user", "parts": [{"text": content}]})
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": content}]})
        if not contents:
            return None
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gk}",
            headers={"Content-Type": "application/json"},
            json={"contents": contents, "systemInstruction": {"parts": [{"text": system_prompt}]},
                  "generationConfig": {"maxOutputTokens": 600, "temperature": 0.7}},
            timeout=15
        )
        result = r.json()
        reply = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        return reply if reply and len(reply) > 5 else None
    except Exception:
        return None

def call_huggingface(hist, system_prompt):
    """Call HuggingFace Inference API - FREE, no key needed for some models"""
    try:
        last_msg = ""
        for h in reversed(hist):
            if h.get("role") == "user":
                last_msg = str(h.get("content",""))
                break
        if not last_msg:
            return None
        prompt = f"{system_prompt}\n\nUser: {last_msg}\nAssistant:"
        r = requests.post(
            "https://api-inference.huggingface.co/models/microsoft/DialoGPT-medium",
            headers={"Content-Type": "application/json"},
            json={"inputs": prompt[:500], "parameters": {"max_new_tokens": 200}},
            timeout=15
        )
        result = r.json()
        if isinstance(result, list) and result:
            reply = result[0].get("generated_text","").replace(prompt,"").strip()
            return reply if reply and len(reply) > 5 else None
        return None
    except Exception:
        return None

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json(silent=True) or {}
        hist = data.get("history", [])
        last_msg = ""
        for h in reversed(hist):
            try:
                if h.get("role") == "user":
                    last_msg = str(h.get("content", ""))
                    break
            except: pass
        # Build memory context
        mem = store.get("ml_memory", [])[-5:]
        mem_txt = ""
        if mem:
            mem_txt = "\n\nUSER RECENT BUDGET DATA:\n"
            for mv in mem:
                try: mem_txt += f"- Income N{mv.get('inc',0)}, Saved N{round(mv.get('savings',0))}\n"
                except: pass
        full_system = SYSTEM + mem_txt

        # === MODEL 1: Anthropic Claude (best quality) ===
        try:
            ak, _ = get_keys()
            if ak and ak.startswith("sk-ant-") and len(ak) > 20:
                r = requests.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": ak, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={"model": "claude-sonnet-4-20250514", "max_tokens": 600,
                          "system": full_system, "messages": hist[-14:]},
                    timeout=20
                )
                result = r.json()
                reply = "".join(b.get("text", "") for b in result.get("content", []) if isinstance(b, dict))
                if reply and len(reply) > 3:
                    return jsonify({"reply": reply, "model": "Claude"})
        except Exception:
            pass

        # === MODEL 2: Groq - LLaMA 3.3 70B (FREE, very fast) ===
        try:
            reply = call_groq(hist, full_system)
            if reply and len(reply) > 5:
                return jsonify({"reply": reply, "model": "LLaMA-3.3"})
        except Exception:
            pass

        # === MODEL 3: Google Gemini Flash (FREE) ===
        try:
            reply = call_gemini(hist, full_system)
            if reply and len(reply) > 5:
                return jsonify({"reply": reply, "model": "Gemini"})
        except Exception:
            pass

        # === MODEL 4: Together AI - Llama 3.1 (FREE tier) ===
        try:
            reply = call_together(hist, full_system)
            if reply and len(reply) > 5:
                return jsonify({"reply": reply, "model": "LLaMA-3.1"})
        except Exception:
            pass

        # === FALLBACK: Smart built-in reply (always works offline) ===
        return jsonify({"reply": smart_reply(last_msg, hist), "model": "offline"})
    except Exception as ex:
        return jsonify({"reply": "Hi! I'm Tanadi. How can I help you today?"})

@app.route("/ml", methods=["POST"])
def ml_route():
    d = request.get_json()
    ns = d.get("nums", [])
    if not ns or ns[0] <= 0: return jsonify({"error": "Need income"})
    return jsonify(ml(ns[0], ns[1] if len(ns)>1 else 0, ns[2] if len(ns)>2 else 0,
                      ns[3] if len(ns)>3 else 0, ns[4] if len(ns)>4 else 0))

@app.route("/ml-memory", methods=["POST"])
def ml_mem():
    d = request.get_json()
    store["ml_memory"].append(d)
    if len(store["ml_memory"]) > 50: store["ml_memory"] = store["ml_memory"][-50:]
    return jsonify({"ok": True})

@app.route("/ai-status", methods=["GET"])
def ai_status():
    """Return which AI models are configured"""
    ak, _ = get_keys()
    gk = get_groq_key()
    tk = get_together_key()
    gmk = get_gemini_key()
    models = []
    if ak and ak.startswith("sk-ant-") and len(ak)>20: models.append("Claude")
    if gk and len(gk)>20: models.append("LLaMA-3.3")
    if gmk and len(gmk)>20: models.append("Gemini")
    if tk and len(tk)>20: models.append("LLaMA-3.1")
    models.append("Offline-AI")
    return jsonify({"active": models[0], "available": models})

@app.route("/clear-chat", methods=["POST"])
def clear_chat():
    store["chat_memory"] = []
    return jsonify({"ok": True})

@app.route("/chat-memory", methods=["POST"])
def chat_mem():
    d = request.get_json()
    store["chat_memory"].append({"q": d.get("q"), "a": d.get("a"),
        "t": datetime.datetime.now().strftime("%d %b %Y %H:%M")})
    if len(store["chat_memory"]) > 100: store["chat_memory"] = store["chat_memory"][-100:]
    return jsonify({"ok": True})

@app.route("/game-coins", methods=["POST"])
def game_coins():
    d = request.get_json()
    coins = int(d.get("coins", 0))
    score = int(d.get("score", 0))
    if coins > 0:
        store["vault"]["balance"] = round(store["vault"]["balance"] + coins, 2)
        store["vault"]["transactions"].append({
            "type": "deposit", "amount": coins,
            "note": f"Game reward: {coins} coins (score {score})",
            "date": datetime.datetime.now().strftime("%d %b %Y %H:%M")
        })
    return jsonify({"ok": True, "vault": store["vault"]["balance"]})

@app.route("/banks")
def banks():
    if not has_ps(): return jsonify({"banks": FALLBACK_BANKS})
    live = ps_banks()
    return jsonify({"banks": live if live else FALLBACK_BANKS})

@app.route("/verify-account", methods=["POST"])
def verify():
    d = request.get_json()
    if not has_ps(): return jsonify({"ok": False, "msg": "Set PAYSTACK_SECRET in tanadi_config.py"})
    return jsonify(ps_verify(d.get("account_number"), d.get("bank_code")))

@app.route("/ps-balance")
def ps_bal():
    if not has_ps(): return jsonify({"ok": False, "msg": "Key not set"})
    return jsonify(ps_balance())

@app.route("/transfer", methods=["POST"])
def transfer():
    d = request.get_json()
    amt = float(d.get("amount", 0))
    if amt <= 0: return jsonify({"ok": False, "msg": "Invalid amount"})
    if not has_ps(): return jsonify({"ok": False, "msg": "Set PAYSTACK_SECRET"})
    return jsonify(ps_transfer(amt, d["account_number"], d["bank_code"], d["bank_name"], d["account_name"], d.get("note", "Tanadi")))

@app.route("/init-payment", methods=["POST"])
def init_pay():
    d = request.get_json()
    amt = float(d.get("amount", 0))
    email = d.get("email", "")
    ref = d.get("ref", "")
    if not amt or not email: return jsonify({"ok": False, "msg": "Amount and email required"})
    if not has_ps(): return jsonify({"ok": False, "msg": "Set PAYSTACK_SECRET in tanadi_config.py"})
    return jsonify(ps_init_payment(amt, email, ref))

@app.route("/verify-payment", methods=["POST"])
def verify_pay():
    d = request.get_json()
    ref = d.get("ref", "")
    if not ref: return jsonify({"ok": False, "msg": "No reference"})
    if not has_ps(): return jsonify({"ok": False, "msg": "Set PAYSTACK_SECRET"})
    result = ps_verify_payment(ref)
    if result.get("ok"):
        store["vault"]["balance"] = round(store["vault"]["balance"] + result["amount"], 2)
        store["vault"]["transactions"].append({
            "type": "received", "amount": round(result["amount"], 2),
            "note": "Received via Paystack",
            "date": datetime.datetime.now().strftime("%d %b %Y %H:%M")
        })
    return jsonify(result)

@app.route("/payment-callback")
def pay_cb():
    ref = request.args.get("reference", "")
    return f"""<html><body style="background:#07101f;color:#e0eefa;font-family:sans-serif;text-align:center;padding:40px">
    <h2 style="color:#00d4aa">Payment Done!</h2><p>Ref: {ref}</p>
    <p>Return to Tanadi and tap <b>I Have Paid</b></p>
    <script>setTimeout(function(){{window.close();}},4000);</script></body></html>"""

@app.route("/vault")
def get_vault(): return jsonify(store["vault"])

@app.route("/vault/deposit", methods=["POST"])
def deposit():
    d = request.get_json()
    amt = float(d.get("amount", 0))
    note = d.get("note", "Deposit")
    if amt > 0:
        store["vault"]["balance"] = round(store["vault"]["balance"] + amt, 2)
        store["vault"]["transactions"].append({
            "type": "deposit", "amount": round(amt, 2), "note": note,
            "date": datetime.datetime.now().strftime("%d %b %Y %H:%M")
        })
    return jsonify(store["vault"])

@app.route("/vault/withdraw", methods=["POST"])
def withdraw():
    d = request.get_json()
    amt = float(d.get("amount", 0))
    note = d.get("note", "Withdrawal")
    if 0 < amt <= store["vault"]["balance"]:
        store["vault"]["balance"] = round(store["vault"]["balance"] - amt, 2)
        store["vault"]["transactions"].append({
            "type": "wit", "amount": round(amt, 2), "note": note,
            "date": datetime.datetime.now().strftime("%d %b %Y %H:%M")
        })
        return jsonify(store["vault"])
    return jsonify({"error": "Insufficient balance"}), 400

if __name__ == "__main__":
    print("\n" + "="*52)
    print("  TANADI AI SAVINGS ASSISTANT v9")
    print("="*52)
    print(f"  AI Chat:  {'OK - Ready' if has_ant() else 'Set ANTHROPIC_KEY in tanadi_config.py'}")
    print(f"  Bank:     {'OK - Ready' if has_ps()  else 'Set PAYSTACK_SECRET in tanadi_config.py'}")
    print()
    print("  Open browser: http://127.0.0.1:5000")
    print("="*52 + "\n")
    app.run(host="127.0.0.1", port=5000, debug=False)
