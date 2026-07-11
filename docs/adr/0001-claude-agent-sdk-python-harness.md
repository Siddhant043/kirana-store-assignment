# Claude Agent SDK (Python) as the agent harness

We build on the Claude Agent SDK in Python. It gives a real observe→reason→act control loop with native multi-tool chaining in one turn (what the brief's §5 requires), first-class tool schemas, and subagent support — while Python has the strongest ecosystem for the two required artifacts (WeasyPrint for GST PDFs, python-pptx for decks). Considered Vercel AI SDK (TS) and "deep agent"; rejected because TS PPTX tooling is weaker and the deep-agent justification story is thinner.
