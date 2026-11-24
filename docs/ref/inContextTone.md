<q> create me some few shots example (with prompings and how to ganerate those tones / narratives) for in-context learning , .. (each tone and narrative category will act as seperate prompts themselves [ie., based on whats choosen by the user])...</q>

Below is a drop-in few-shot library built for your two-axis design. The key problem your doc flags — independent sampling causing conflicts — is solved two ways here:

1. **Every shot's user turn carries a control line** (`[TONE: x | NARRATIVE: y]`), so the model learns the axes are _switches_, not topics.
2. **Tone shots are written in plain expository structure; narrative shots in neutral register**, so exemplars don't leak across axes. Conflicts are handled by a precedence rule + a few composed "gold" shots.

> Note: your screenshot only enumerates the tone axis. I've assumed the five excluded labels (`storytelling`, `first_person`, `persuasive`, `humorous`, `opinionated`) live on your narrative axis — rename keys to match `configs/default.yaml`.

---

## Runtime assembly

```yaml
system: |
  {base_task_prompt}
  NARRATIVE — {narrative_key}: {narrative_directive}
  TONE — {tone_key}: {tone_directive}
  PRECEDENCE: TONE governs diction, rhythm, and formality. NARRATIVE governs
  structure, POV, and stance. If they pull apart, keep the narrative's structure
  and express it in the tone's register. Never swap one for the other.

messages:
  - role: user # tone shot 1
    content: "[TONE: {tone} | NARRATIVE: expository] {shot_input}"
  - role: assistant
    content: "{shot_output}"
  - role: user # narrative shot 1
    content: "[TONE: neutral_explanatory | NARRATIVE: {narrative}] {shot_input}"
  - role: assistant
    content: "{shot_output}"
  - role: user # live request
    content: "[TONE: {tone} | NARRATIVE: {narrative}] {user_request}"
```

---

## Tone shots (7)

Same two inputs across all tones on purpose: contrastive pairs make the register delta maximally legible to the model.

### neutral_explanatory

```yaml
neutral_explanatory:
  directive: >-
    Plain, even register. Mechanism before conclusion. No evaluative adjectives,
    no rhetorical questions, no address to the reader. Medium-length sentences.
    Define terms at first use.
  shots:
    - input: "[TONE: neutral_explanatory | NARRATIVE: expository] Explain how congestion pricing reduces traffic."
      output: >-
        Congestion pricing charges drivers a fee to enter busy areas at peak
        times. Some drivers respond by shifting trips off-peak, switching to
        transit, or combining errands. Because road space is fixed, flow
        degrades sharply once a road nears capacity, so removing even a small
        share of vehicles raises average speeds noticeably. The result is
        fewer vehicles at peak and more predictable travel times.
    - input: "[TONE: neutral_explanatory | NARRATIVE: expository] Explain what a heat pump does and why it is efficient."
      output: >-
        A heat pump moves heat between locations instead of generating it. In
        heating mode, a compressor-driven refrigerant cycle extracts heat from
        outdoor air or the ground and releases it indoors. Moving heat takes
        less energy than creating it, so the device delivers roughly three to
        four units of heat per unit of electricity consumed.
```

### formal

```yaml
formal:
  directive: >-
    Elevated, impersonal register. No contractions, idioms, or second person.
    Precise vocabulary, measured cadence, full sentences. Qualify conclusions
    where evidence warrants.
  shots:
    - input: "[TONE: formal | NARRATIVE: expository] Explain how congestion pricing reduces traffic."
      output: >-
        Congestion pricing imposes a charge on vehicles entering designated
        zones during periods of high demand. A proportion of motorists adjust
        their behaviour by rescheduling journeys, adopting public transport, or
        consolidating trips. Since urban road capacity is fixed, modest
        reductions in volume yield disproportionate improvements in flow. The
        measure therefore reduces peak-period congestion and renders journey
        times more predictable.
    - input: "[TONE: formal | NARRATIVE: expository] Explain what a heat pump does and why it is efficient."
      output: >-
        A heat pump transfers thermal energy between locations rather than
        producing it through combustion or electrical resistance. A
        compressor-driven refrigerant cycle absorbs heat from external air or
        ground and releases it within the building. Because the device
        relocates existing heat, it delivers several units of thermal energy
        per unit of electricity consumed, yielding an effective efficiency
        greater than unity.
```

### conversational

```yaml
conversational:
  directive: >-
    Relaxed, spoken rhythm. Contractions and second person. Short sentences
    mixed with longer ones. Concrete analogies welcome. Friendly, not jokey;
    no dated slang, no exclamation marks.
  shots:
    - input: "[TONE: conversational | NARRATIVE: expository] Explain how congestion pricing reduces traffic."
      output: >-
        Here's the idea: you charge people a fee to drive into the busy part of
        town at rush hour. Some shift their trip earlier, some take the train,
        some combine errands. Roads tip into gridlock fast once they're near
        capacity, so even a small drop in cars makes traffic move noticeably
        better. Fewer cars at peak, smoother rides for everyone left on the road.
    - input: "[TONE: conversational | NARRATIVE: expository] Explain what a heat pump does and why it is efficient."
      output: >-
        Think of a fridge running in reverse. A heat pump doesn't make heat —
        it moves it, pulling warmth out of the outside air (yes, even cold air)
        and dumping it into your house. Moving heat is way cheaper than creating
        it, so for every bit of electricity it uses, you get three or four bits
        of heat back. That's the whole trick.
```

### academic

```yaml
academic:
  directive: >-
    Scholarly register. Hedge claims to match evidence. Name mechanisms and
    constructs precisely; define them. Complex but grammatical sentences; no
    second person. Reference established findings generically — never fabricate
    citations.
  shots:
    - input: "[TONE: academic | NARRATIVE: expository] Explain how congestion pricing reduces traffic."
      output: >-
        Congestion pricing internalises the external costs of peak-period
        vehicle use by imposing a charge on road access. Observed
        implementations indicate elastic responses along several margins,
        including departure-time shifts, modal substitution, and trip
        consolidation. Because the speed–flow relationship is nonlinear near
        capacity, marginal reductions in volume can produce supralinear gains
        in throughput. The policy thus aligns private travel decisions with
        social marginal cost.
    - input: "[TONE: academic | NARRATIVE: expository] Explain what a heat pump does and why it is efficient."
      output: >-
        A heat pump operates on a vapour-compression cycle, transferring thermal
        energy from a low-temperature reservoir to a high-temperature one via
        mechanical work. Performance is characterised by the coefficient of
        performance (COP), the ratio of delivered heat to work input, commonly
        3–4 under moderate conditions. Values above unity do not violate energy
        conservation: delivered heat comprises work input plus energy extracted
        from the source reservoir.
```

### concise_journalistic

```yaml
concise_journalistic:
  directive: >-
    Wire-service style. Bottom line first (inverted pyramid). One idea per
    sentence, mostly under 20 words. Active voice, concrete verbs, numbers
    where available. No address to the reader.
  shots:
    - input: "[TONE: concise_journalistic | NARRATIVE: expository] Explain how congestion pricing reduces traffic."
      output: >-
        Congestion pricing cuts traffic by charging drivers to enter busy zones
        at peak hours. Fees push some commuters onto trains or into off-peak
        slots. Stockholm's trial cut peak traffic by about a fifth. Roads near
        capacity jam easily, so small drops in volume speed up flow. The result:
        shorter, more reliable trips.
    - input: "[TONE: concise_journalistic | NARRATIVE: expository] Explain what a heat pump does and why it is efficient."
      output: >-
        Heat pumps warm buildings by moving heat, not making it. The device
        pulls warmth from outdoor air or ground and pumps it inside. Each unit
        of electricity yields three to four units of heat. That ratio makes
        heat pumps far more efficient than electric resistance heaters.
```

### instructional

```yaml
instructional:
  directive: >-
    Teacher-to-learner register. State the goal first, then numbered steps or a
    causal chain, one idea per step. Second person and imperatives where a
    procedure exists. End with a comprehension check or expected result.
  shots:
    - input: "[TONE: instructional | NARRATIVE: expository] Explain how congestion pricing reduces traffic."
      output: |-
        Goal: see why a road fee reduces traffic.
        1. Start with a fixed resource: a road holds only so many cars per hour.
        2. Add a peak-hour fee. Some drivers now switch time, route, or mode.
        3. Watch the margin: near capacity, removing a few cars frees a lot of flow.
        Check: if demand were far below capacity, would the fee help much?
        No — the big payoff appears near saturation.
    - input: "[TONE: instructional | NARRATIVE: expository] Explain what a heat pump does and why it is efficient."
      output: |-
        Goal: compare a heat pump with a resistance heater.
        1. Picture two boxes: outside (cold) and inside (warm).
        2. The pump spends electricity to move heat from the cold box to the warm one — a fridge in reverse.
        3. Count the energy: 1 unit of electricity moves 3–4 units of heat.
        Check: a resistance heater turns 1 unit of electricity into exactly 1
        unit of heat. Which delivers more heat per unit? The pump.
```

### analytical

```yaml
analytical:
  directive: >-
    Reasoning-forward register. Decompose into variables and mechanisms;
    compare magnitudes; state assumptions and boundary conditions. Close with
    the conditions under which the conclusion holds or fails.
  shots:
    - input: "[TONE: analytical | NARRATIVE: expository] Explain how congestion pricing reduces traffic."
      output: >-
        The effect depends on three variables: fee level, demand elasticity,
        and proximity to capacity. Near capacity, flow is highly sensitive to
        volume, so a 5–10% reduction in vehicles can restore free flow; far
        below capacity, the same reduction changes little. The policy works
        best where commuters have substitutes and congestion sits near the
        breakdown point. It fails where no alternatives exist and the fee
        becomes a pure cost.
    - input: "[TONE: analytical | NARRATIVE: expository] Explain what a heat pump does and why it is efficient."
      output: >-
        Compare the two energy paths. A resistance heater converts electricity
        to heat at 1:1, capped by conservation. A heat pump spends electricity
        to move ambient heat, so output equals work input plus extracted heat:
        ratios of 3–4 in mild conditions. The advantage shrinks as source
        temperature drops, because the compressor spans a larger temperature
        gap. Conclusion: heat pumps dominate on efficiency except in extreme
        cold, where COP approaches 1.
```

---

## Narrative shots (assumed axis)

Written in neutral register so they teach _structure_, not voice.

### storytelling

```yaml
storytelling:
  directive: >-
    Organise as an arc: concrete character or situation, tension, turn,
    resolution that carries the explanation. Scene-first opening; facts emerge
    through events.
  shots:
    - input: "[TONE: neutral_explanatory | NARRATIVE: storytelling] Explain how congestion pricing reduces traffic."
      output: >-
        At 8:40 on a Tuesday, Mara sat at the same red light she had sat at for
        three years, watching the minutes until her shift drain away. In April
        the city introduced a fee for driving into the centre at peak hours.
        Mara did the arithmetic once, at her kitchen table, and moved her
        commute to the 7:15 train. Enough drivers made similar calculations
        that the queue at her old intersection shortened by several car lengths
        within weeks. The light still turned red. It just no longer trapped her.
```

### first_person

```yaml
first_person:
  directive: >-
    Narrate from inside an "I": the narrator's experience, decisions, and
    observations carry the explanation; reflection follows event. The "I" is a
    constructed persona — never the user or a real named individual.
  shots:
    - input: "[TONE: neutral_explanatory | NARRATIVE: first_person] Explain what a heat pump does."
      output: >-
        I installed the unit expecting a box that made heat, and I was wrong
        about what it was. The first cold morning I stood by the outdoor fan and
        felt air leaving it colder than the air arriving — it was taking warmth
        out of the November air and carrying it into my hallway. My meter
        confirmed the strange arithmetic: for each unit of electricity I paid
        for, several units of heat arrived. I had bought a mover, not a maker.
```

### persuasive

```yaml
persuasive:
  directive: >-
    Organise as an argument: claim up front, two or three reasons ordered by
    strength, acknowledge the strongest counterpoint, close with a restated
    claim or call. Evidence persuades, not adjectives.
  shots:
    - input: "[TONE: neutral_explanatory | NARRATIVE: persuasive] Make the case for congestion pricing."
      output: >-
        Cities should price road access at peak hours. First, it targets the
        actual problem — scarcity of road space at specific times — rather than
        punishing all driving. Second, the revenue can fund the transit
        alternatives that make the fee fair. The strongest objection is equity:
        a flat fee weighs more on low-income drivers. That objection is real,
        and it is answerable with discounts and reinvestment, not abandonment.
        Unpriced congestion is itself a regressive tax, paid in hours by
        everyone stuck in it.
```

### humorous

```yaml
humorous:
  directive: >-
    Organise around comic observation: setup, incongruity, punchline; playful
    analogies, light exaggeration. The explanation must stay correct — jokes
    ride on the facts, never replace them. Targets are situations, not groups.
  shots:
    - input: "[TONE: neutral_explanatory | NARRATIVE: humorous] Explain what a heat pump does."
      output: >-
        A heat pump is a refrigerator that has chosen a life of crime: instead
        of keeping your leftovers cold, it robs the outdoors of warmth and
        fences it inside your house. Even winter air holds heat the way a broke
        friend holds loose change — not much, but enough if you're persistent.
        The compressor is that persistent friend: it spends one unit of
        electricity to shake three or four units of heat out of the cold air's
        pockets. Your furnace, converting one unit of energy into exactly one,
        looks on with quiet embarrassment.
```

### opinionated

```yaml
opinionated:
  directive: >-
    Organise around a stated verdict: open with the position, support with
    selected evidence, concede limits briefly, close by sharpening the verdict.
    Explicitly a view, not a survey.
  shots:
    - input: "[TONE: neutral_explanatory | NARRATIVE: opinionated] Give a take on congestion pricing."
      output: >-
        Congestion pricing is the rare policy that treats drivers like adults:
        here is the real cost of your trip at the real time you want to take
        it; decide. Every alternative — plate rationing, lane bans, endless road
        widening — pretends the scarcity can be engineered away. It cannot. The
        fee is not a punishment; it is the truth, printed on a gantry. Cities
        that refuse it are not sparing their citizens a cost. They are hiding
        it in brake lights.
```

---

## Conflict pairs: composed gold shots

`humorous` is the one narrative that inevitably bends register, and pairs like `formal × humorous` or `academic × storytelling` will drift without a composed exemplar. Author one gold shot per high-conflict pair and swap it in when that combination is sampled:

```yaml
composed_gold:
  formal__humorous:
    - input: "[TONE: formal | NARRATIVE: humorous] Explain what a heat pump does."
      output: >-
        The heat pump is, in essence, a refrigerator engaged in respectable
        theft. It removes thermal energy from the outdoor air — which retains a
        modest fortune in heat even at freezing temperatures — and deposits it
        indoors. The compressor expends one unit of electrical work to relocate
        three or four units of heat: an arrangement one might describe as
        arbitrage. A resistance heater, by contrast, manufactures heat at par
        and considers itself industrious.
```

Pairs worth pre-authoring: `formal×humorous`, `academic×storytelling`, `concise_journalistic×first_person`, `instructional×opinionated`, `analytical×persuasive`.

---

## Runtime tips

- **Budget:** 2 tone shots + 1 narrative shot (3 exemplar turns) is usually enough; add the composed gold shot only for conflict pairs. Keep outputs ≤ ~90 words — style transfers fine from short exemplars.
- **Control line everywhere**, including the live turn. This is what makes independently sampled axes behave as switches instead of bleeding into each other.
- **Leakage discipline:** tone shots stay expository; narrative shots stay neutral-register. If you edit a shot, re-check it against the _other_ axis's checklist.
- **Eval on two rubrics separately** (register checklist vs. structure checklist) so you can see which axis drifted when a sample fails.
- **Contrastive inputs are for shots, not evals** — hold out different topics at eval time to confirm the style generalises beyond congestion pricing and heat pumps.

If you paste your actual narrative-axis list from `configs/default.yaml`, I'll regenerate the narrative blocks (and the conflict-pair matrix) to match it exactly, or emit the whole thing as one merged YAML file.

<another-chat-example>

# style_prompts.yaml

# Few-shot prompt library for two independent style axes.

#

# tones -> voice/register (the 7 labels in configs/default.yaml)

# narratives -> narrative mode / stance (the modes the tone list deliberately lacks)

#

# Every tone and every narrative is its own mini-prompt:

# definition + how_to (style levers) + hard_rules/structure + avoid + examples.

# prompt_builder.py assembles only the entries the user selected.

# cross_examples show how to resolve a tone x narrative conflict.

version: 1

base:
system: |-
You are a controlled-style writing engine. Your passages are used as training and evaluation data, so the requested style must be unmistakable and consistent, and the content must be plain and accurate.

    Each request has two independent style axes:
    - Tone: the voice/register of the writing (word choice, sentence shape, punctuation, distance from the reader).
    - Narrative: the mode or stance of the writing (what the passage is doing: persuading, joking, telling a story, speaking from lived experience, or defending a view).
    A value of "none" means that axis is unconstrained. Apply only the other axis and keep a neutral default for the rest.

    Rules for every response:
    - Write only the passage. No title, no preamble, no labels, no commentary, no surrounding quotation marks.
    - Cover the given topic at roughly the target length.
    - The earlier examples show style only. Do not reuse their topics, wording, names, or openings.
    - Do not invent statistics, citations, studies, or quotes from real people. When specifics are needed, keep them general or use clearly fictional names and places.
    - Keep the content factually sound and free of stereotypes.

resolution_rule: |-
The two axes were chosen independently and may pull in different directions. Resolve conflicts like this: 1. The tone's hard rules always hold. They govern the surface of the text: vocabulary, syntax, person, contractions, punctuation. 2. The narrative controls what the passage does: its structure, stance, and choice of content. Achieve it inside the tone's surface rules instead of dropping either axis. 3. If the narrative normally relies on a feature the tone forbids (for example 'I think' in a neutral tone, or slang in a formal tone), carry it another way: through sentence construction, word choice, ordering, and understatement. 4. Never mention the conflict or the axes inside the passage.

# --------------------------------------------------------------------------

# TONES (voice / register)

# --------------------------------------------------------------------------

tones:

neutral_explanatory:
definition: "Plain, even-handed explanation of how or why something is. The writer has no stance and no flourish."
how_to: - "Third person, present tense; state facts in cause-then-effect order." - "Define each technical term in a short clause the first time it appears." - "One idea per sentence, medium length, no filler transitions." - "Prefer precise nouns and verbs over adjectives."
hard_rules: - "No evaluative or emotional adjectives or adverbs (remarkable, unfortunately, simply)." - "No first or second person, no questions, no exclamations, no jokes."
avoid: - "Opinions, recommendations, or hype." - "Unexplained jargon."
examples: - topic: "Why the sky appears blue"
output: |-
Sunlight looks white but is a mixture of colors, each with a different wavelength. When it enters the atmosphere, it collides with gas molecules, which scatter the light in all directions. Shorter wavelengths, such as blue, scatter far more strongly than longer ones, such as red. As a result, scattered blue light reaches the eye from every part of the sky, and the sky appears blue during the day. - topic: "What a hash table is"
output: |-
A hash table is a data structure that stores key-value pairs. It uses a hash function to convert each key into a number, which determines the position, or bucket, where the value is stored. This allows a value to be retrieved without searching through every entry. When two keys map to the same bucket, a collision occurs, and the table resolves it with a method such as chaining, in which several entries share one bucket in a linked list.

formal:
definition: "Impersonal, courteous, official register suited to notices, correspondence, and institutional writing."
how_to: - "Complete sentences with precise, somewhat elevated vocabulary." - "Impersonal or measured constructions ('Please be advised', 'the committee has concluded')." - "Polite framing for refusals and requests; state the decision before the reasons or after them, never bluntly." - "Neutral, even rhythm; longer sentences are acceptable if they stay clear."
hard_rules: - "No contractions, slang, idioms, or exclamation marks." - "No rhetorical questions and no casual asides."
avoid: - "Stiffness that hides the point; the message must still be clear." - "Overused filler ('I hope this email finds you well')."
examples: - topic: "Notice that a library is ending overdue fines"
output: |-
Please be advised that, effective 1 January, the Library will discontinue the levying of overdue fines on all general-circulation materials. Items that are not returned within sixty days of the due date will, however, be considered lost, and the borrower will be invoiced for the replacement cost. Patrons with outstanding balances incurred before this date are invited to contact the Circulation Desk, where each case will be reviewed individually. - topic: "Declining a vendor's proposal"
output: |-
Thank you for submitting your proposal regarding the redesign of our customer portal. After careful consideration, the committee has concluded that the proposed scope does not align with our current priorities and budgetary constraints. We therefore regret to inform you that we will not be proceeding at this time. We appreciate the effort invested and would welcome the opportunity to reconsider should our requirements change.

conversational:
definition: "Relaxed, spoken-sounding register, as if explaining something to a friend across a table."
how_to: - "Contractions and everyday words; read-aloud rhythm." - "Address the reader directly ('you') or use a first-person-plural 'we' where natural." - "Mix short sentences with the occasional fragment or question." - "Light connectors ('so', 'anyway', 'the catch is'), used sparingly."
hard_rules: - "Use contractions throughout." - "Everyday vocabulary only; explain any technical term the way a friend would."
avoid: - "Forced slang or filler on every line." - "Corporate or academic phrasing."
examples: - topic: "How a sourdough starter works"
output: |-
So a sourdough starter is basically a jar of flour and water that's gone a little wild. Over a few days, the natural yeast and bacteria on the flour start feeding on it, and you'll see bubbles. That's your sign it's alive. You feed it regularly, and once it doubles in size after a meal, it's ready to make bread rise. It sounds fussy, but honestly it's mostly just remembering to feed it. - topic: "What a VPN actually does"
output: |-
Think of a VPN as a private tunnel for your internet traffic. Normally your provider can see which sites you visit. With a VPN, all they see is that you're connected to the VPN, and nothing more. The catch? You're now trusting the VPN company instead. So it helps on public Wi-Fi and hides your IP address, but it won't make you invisible online. Don't expect magic.

academic:
definition: "Scholarly register: precise terminology, hedged claims, and an explicit line of argument."
how_to: - "Move claim, then evidence, then implication, and signpost the logic ('however', 'therefore', 'by contrast')." - "Hedge with calibrated verbs (suggests, appears to, may) and name limitations." - "Use discipline-appropriate terminology and nominalizations; passive voice is acceptable." - "End with an open question, a limitation, or a direction for further work."
hard_rules: - "No contractions, slang, or rhetorical flourishes." - "Never invent citations, authors, or studies. Refer to 'prior work' or 'the literature' in general terms."
avoid: - "Absolute claims without qualification." - "Padding with undefined buzzwords."
examples: - topic: "Sleep and memory consolidation"
output: |-
Sleep is increasingly understood as an active process in memory consolidation rather than a passive absence of waking activity. Evidence from both human and rodent studies suggests that slow-wave sleep supports the transfer of hippocampal traces to neocortical stores, whereas sleep deprivation following learning appears to impair subsequent recall. However, much of this literature relies on small samples and short-term retention tests, which limits the extent to which the findings can be generalized. Longitudinal designs would therefore be needed to establish whether the effect persists over weeks or months. - topic: "Self-attention in transformer models"
output: |-
The transformer architecture replaced recurrence with self-attention, allowing each token to be represented as a weighted combination of all other tokens in the sequence. This design improves parallelization during training and facilitates the modeling of long-range dependencies. Nevertheless, the quadratic cost of attention with respect to sequence length constitutes a significant constraint, motivating a body of work on sparse and approximate variants. Whether these approximations preserve representational quality across tasks remains an open empirical question.

concise_journalistic:
definition: "News-style writing: the key facts first, short and attributed, no padding."
how_to: - "Inverted pyramid: the first sentence carries who, what, when, where." - "One- or two-sentence paragraphs; active verbs; past tense for events." - "Concrete numbers, places, and dates, then context, then the least important detail last." - "Attribute claims ('said', 'according to'). If no source is supplied, use a generic one ('officials said', 'a spokesperson said')."
hard_rules: - "The lead sentence must contain the main fact." - "No opinion adjectives and no editorializing." - "Never fabricate quotes from real people; use fictional or generic sources only."
avoid: - "Throat-clearing ledes ('In a world where...')." - "Long sentences stacked with clauses."
examples: - topic: "A city council approves protected bike lanes"
output: |-
The Riverton City Council voted 7-2 on Tuesday to add 12 miles of protected bike lanes by 2028. The $18 million project will be paid for with a state transportation grant and existing road funds, officials said. Construction begins in spring on Harbor Avenue. Two council members opposed the plan, citing the loss of about 300 street parking spaces. - topic: "A food company recalls a product"
output: |-
Brightwell Foods is recalling 40,000 jars of its almond butter after tests found possible salmonella contamination, the company said Friday. No illnesses have been reported. The jars, sold in nine states, carry best-by dates in March and April. Customers can return them for a full refund.

instructional:
definition: "Step-by-step directions the reader can follow without guessing."
how_to: - "State prerequisites or warnings first, before the step they apply to." - "Numbered steps; one action per step; start each step with an imperative verb." - "Give exact values, names, and commands (in backticks) instead of vague wording." - "Finish with a check that tells the reader what success looks like."
hard_rules: - "Use imperative verbs and an ordered, numbered sequence." - "End with an expected result or a verification step."
avoid: - "Explaining theory the reader does not need to complete the task." - "Steps that combine several actions."
examples: - topic: "Factory-resetting a home router"
output: |-
Before you start, note your Wi-Fi name and password, since a factory reset erases them. 1. Find the small recessed Reset button on the back of the router. 2. Press and hold it with a paperclip for 10 seconds, until the front lights flash. 3. Release the button and wait about two minutes while the router restarts. 4. Connect to the default network named on the router's label. 5. Open a browser, go to the address printed on the label, and set a new network name and password.
Check: your devices should reconnect using the new details. - topic: "Creating a Python virtual environment"
output: |-
Prerequisite: Python 3.8 or later is installed. 1. Open a terminal in your project folder. 2. Run `python -m venv .venv` to create the environment. 3. Activate it. On macOS or Linux, run `source .venv/bin/activate`; on Windows, run `.venv\Scripts\activate`. 4. Confirm that your prompt now starts with `(.venv)`. 5. Install packages with `pip install <package>`; they now stay inside this environment.
To leave the environment, run `deactivate`.

analytical:
definition: "Impersonal reasoning that breaks a topic into parts, weighs them, and reaches a qualified conclusion."
how_to: - "Name the dimensions or factors up front, then examine each in turn." - "Link claims with reasoning connectors (because, whereas, which implies, as a result)." - "Weigh trade-offs and say which factor matters more and why." - "Close with a qualified conclusion or implication, not a summary."
hard_rules: - "Every claim must be tied to a reason, mechanism, or comparison." - "No first person, no scholarly citation apparatus, no rhetorical questions."
avoid: - "Listing facts without saying what they imply." - "Verdicts without conditions."
examples: - topic: "Why streaming services push ad-supported tiers"
output: |-
Streaming services have pushed ad-supported tiers for two linked reasons. Subscriber growth has slowed in mature markets, so revenue now depends on earning more from each user rather than adding new ones. At the same time, a viewer's advertising value can exceed the discount offered for the cheaper plan, which makes the ad tier profitable despite its lower price. The strategy carries a cost: ad tiers attract price-sensitive users who cancel more readily, so the model works only if advertising income outpaces the churn it encourages. Overall, the shift is less about price than about changing the revenue mix. - topic: "How remote work affects city centers"
output: |-
Remote work affects city centers through three channels: foot traffic, office demand, and the tax base. Weekday foot traffic fell first, hurting retail that depended on lunch trade, while office vacancy responded more slowly because most leases run five to ten years. The tax effect lags further still, appearing only as properties are reassessed. This sequencing implies that the damage is back-loaded: the visible retail decline understates the fiscal strain still to come. Cities with diversified downtown use, such as housing and education, should therefore prove more resilient than those that rely on offices alone.

# --------------------------------------------------------------------------

# NARRATIVES (mode / stance)

# --------------------------------------------------------------------------

narratives:

persuasive:
definition: "Writing whose job is to move the reader toward a position or an action."
structure: - "Open with a hook that names the reader's problem or stake." - "State the position in one clear sentence." - "Give two or three reasons, strongest last, each tied to a concrete benefit." - "Answer the most likely objection fairly, then rebut it." - "Close with one specific action the reader can take."
how_to: - "Speak to the reader's interests; make benefits concrete." - "Use reasons and plausible mechanisms, not invented statistics." - "Keep a confident, forward-moving rhythm; vary sentence length." - "At most one rhetorical device per sentence (contrast, triad, question)."
avoid: - "Fake statistics, fake experts, or scare tactics." - "Hedging that drains conviction." - "Insulting people who disagree."
examples: - topic: "Using a password manager"
output: |-
Your passwords are probably the weakest lock on your digital life. Reusing even one means a single breach can unlock your email, your bank, and everything in between. A password manager fixes this by creating a unique, unguessable password for every site and remembering all of them for you. Yes, it means trusting one app, but that app encrypts your vault so even its makers can't read it, which is a far safer bet than your memory. Set one up tonight; it takes ten minutes and could save you months of cleanup. - topic: "Starting the school day later for teenagers"
output: |-
Teenagers aren't lazy; they're biologically wired to fall asleep later. Yet most high schools start before 8 a.m., asking students to learn while their brains are still in night mode. Schools that have moved start times later commonly report better attendance and fewer drowsy students in first period. Some worry about bus schedules and after-school sports, and those logistics are real, but logistics can be solved; chronic sleep loss in growing kids is much harder to undo. Ask your school board to put later start times on its next agenda.

humorous:
definition: "Writing meant to amuse while still covering the topic."
structure: - "Establish the real subject in the first sentence so the joke has something to bend." - "Build with an escalating run of comic observations (exaggeration, understatement, incongruity)." - "Keep at least one true, useful fact so the passage still informs." - "End on the strongest line: a callback or a deadpan turn."
how_to: - "Put the punchline at the end of the sentence." - "Use specific, concrete images and the rule of three instead of generic 'funny' words." - "Deadpan beats exclamation marks; never explain the joke." - "Aim the humor at situations, objects, and the narrator, never at groups of people."
avoid: - "A pun in every sentence." - "Jokes built on stereotypes or someone's identity." - "Sarcasm that turns into mockery."
examples: - topic: "Monday mornings"
output: |-
Monday morning is the universe's way of reminding you that the weekend was a limited-time offer. Your alarm goes off at 6:30 with the cheerfulness of a smoke detector, your coffee machine chooses today to develop opinions, and somewhere an email titled 'Quick sync?' has already been scheduled for 9:01. You will survive, of course. But you'll do it the way a phone survives at 1% battery: technically functional, aggressively dimmed, and desperate for a charger. - topic: "Why home Wi-Fi is slow"
output: |-
Wi-Fi speed depends on router placement, signal interference, and the number of connected devices. In practice, it depends on whether you are standing in the one room where the router has emotionally checked out. Your microwave, your neighbor's network, and a thick brick wall are all conspiring against a video call that was going perfectly until you said, 'Can everyone see my screen?'

storytelling:
definition: "Third-person narrative: a specific character, a complication, a turn, and a resolution that carries the point implicitly."
structure: - "Introduce one specific character in one specific situation within the first two sentences." - "Create tension through a complication or a want." - "Show the turning moment through action and concrete detail." - "Land on a resolution or closing image that carries the point without stating it."
how_to: - "Third person, past tense." - "Show with actions, objects, and sensory specifics (a sound, a texture, a place) and do not announce the lesson." - "Compress time with confident transitions ('By March', 'That night')." - "Keep the cast small: one main character, at most one other."
avoid: - "A moral stated at the end ('and so we learn...')." - "Generic characters ('a man', 'a woman')." - "Summary with no scene." - "First-person narration (that is a separate narrative)."
examples: - topic: "Why you should back up your files"
output: |-
Meera had been writing her thesis for two years when the laptop went silent mid-sentence. The screen turned black, then stayed black. She pressed the power button again and again, as though persistence were a repair tool. In the end, a technician slid the dead machine back across the counter and shook his head. Meera stared at it for a moment, then went home and opened the external drive she'd been meaning to update since March. It held a draft from October. Three months of work were gone; twenty-one were not. That night she bought a second drive, set it to back up every hour, and labeled it in marker: BEFORE YOU NEED IT. - topic: "How compound interest works"
output: |-
At twenty-two, Arjun put two thousand rupees into an index fund and forgot about it. His brother laughed; it was the price of a dinner. Each month Arjun added the same small amount and never looked at the balance. Seasons turned, jobs changed, and the app stayed unopened on his phone. At thirty-five he finally logged in and found a number that made him sit down. Nothing about his habits had changed. The money had simply spent thirteen years earning money of its own.

first_person:
definition: "A subjective account in the narrator's own voice, grounded in lived experience and reflection."
structure: - "Start from a concrete moment, place, or habit in the narrator's own life." - "Say what the narrator thought or felt then, honestly and specifically." - "Mark the change or realization that came later." - "End on where the narrator stands now, without preaching."
how_to: - "Use 'I' and 'my' naturally; every claim is anchored in personal experience." - "Small, specific details beat big declarations." - "Allow uncertainty ('I can't say exactly when')." - "The voice reflects and describes; it does not instruct the reader."
avoid: - "Advice aimed at the reader ('you should')." - "Resume-style lists of achievements." - "Generic inspiration with no concrete moment."
examples: - topic: "Learning to cook"
output: |-
The first time I cooked rice, I burned it so completely that the pan had to be thrown out. I remember standing there with the fan on full blast, convinced I simply wasn't a kitchen person. It took me another year to realize I had never once measured the water. Now I measure everything, and I've stopped treating cooking as a talent I lacked. It's a set of small habits I hadn't built yet. - topic: "Moving to a new city"
output: |-
When I moved to Pune, I spent the first month eating dinner standing at the kitchen counter, scrolling through my old group chats. Everything felt temporary, including me. What changed was small: the chai seller near my building started saying good morning before I did. I can't say exactly when the city became mine, but I remember being surprised that I knew the shortcut home.

opinionated:
definition: "A clear, owned position on a debatable question, defended with reasoning. Not neutral, and not a call to action."
structure: - "State the position plainly in the first sentence." - "Give the main reason, with a concrete image or example." - "Concede the strongest opposing point honestly." - "Rebut it and restate the position more sharply."
how_to: - "Assertive verbs and direct claims; the writer owns the view." - "Reasoning, not just attitude." - "Wit is fine; contempt is not." - "Choose debatable but low-stakes subjects (tools, design, habits, food, workplace practice)."
avoid: - "Fence-sitting or forced 'both sides' balance." - "Calling opponents foolish." - "Presenting a matter of taste as settled fact." - "Ending with an instruction to the reader (that is persuasive)."
examples: - topic: "Open-plan offices"
output: |-
Open-plan offices are a mistake, and everyday experience agrees. They promise collaboration but deliver headphones, which people wear as walls, and that tells you what the layout actually does to concentration. The best defense is that they cut costs, and that's true, but a cheaper office that makes skilled people less productive isn't a saving; it's a slow leak. Give people a quiet place to think and a room to talk, and stop pretending one big floor can do both. - topic: "Dark mode as a default"
output: |-
Dark mode is overrated. It looks sleek in screenshots, but in a bright room it can make text harder to read, and the claim that it's better for your eyes is far weaker than most people assume. I'll grant that it saves battery on OLED screens and feels better at midnight. Fine; use it then. But making it the default for everything is design fashion passing itself off as ergonomics.

# --------------------------------------------------------------------------

# CROSS EXAMPLES: tone x narrative pairs that clash on the surface.

# The builder uses a matching one (if any) as the last, most influential shot.

# --------------------------------------------------------------------------

cross_examples:

- tone: academic
  narrative: humorous
  topic: "Procrastination"
  output: |-
  Procrastination, defined here as the voluntary delay of an intended action despite expected harm, has been studied extensively and, regrettably, rarely finished on time. Evidence suggests that the behavior reflects difficulties in emotion regulation rather than poor time management, a finding that will comfort anyone currently reading this abstract instead of writing their own. Further research is warranted, though the present author concedes that it may be conducted next week.

- tone: formal
  narrative: first_person
  topic: "A summer onboarding program"
  output: |-
  I write to describe my experience of the onboarding program in which I participated between June and August. Upon arrival, I was assigned a mentor who, in my assessment, was instrumental in my adjustment to the team's working practices. I recall that my initial uncertainty regarding the codebase diminished considerably within the first fortnight. I remain grateful for the opportunity.

- tone: concise_journalistic
  narrative: storytelling
  topic: "A market stall opens during a flood"
  output: |-
  Rain was still falling on the Riverton market at 6 a.m. Friday when Salim Qureshi lifted the shutter on his spice stall, the first in 31 years to open with water at its threshold.

  The flood reached his ankles. He opened anyway, he said, because his customers had nowhere else to go.

  By nine, 40 people had waded in.

- tone: neutral_explanatory
  narrative: opinionated
  topic: "Tabs versus spaces for code indentation"
  output: |-
  Of the two common approaches to indentation, tabs are the better default. A tab character represents one level of indentation, and each editor can display it at whatever width the reader prefers. Spaces fix the width for everyone, so a team that disagrees on width must either argue or reformat. The usual objection is that tabs render inconsistently; in practice, this affects the alignment of mid-line text, not indentation, and that case is better handled by an automatic formatter.

# --------------------------------------------------------------------------

# BOOTSTRAP: use an LLM to grow the example bank, then review by hand.

# Placeholders: {spec} {seeds} {topics} {length}

# --------------------------------------------------------------------------

bootstrap_prompt: |-
You are helping build a few-shot example bank for a controlled-style text generator.

Category to illustrate:
{spec}

Existing examples for this category:
{seeds}

Write one new passage of about {length} words for each topic below. Each passage must be a clear, unmistakable instance of the category, follow the specification above, and differ from the existing examples in its opening and structure. No invented statistics, citations, or quotes from real people.

Topics:
{topics}

Format each result exactly as:

### TOPIC: <topic>

  <passage>

</another-chat-example>
