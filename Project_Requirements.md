<!-- PDF page 1 -->

# Project Announcement: Agentic Systems

Course: 503N / 798S

Instructor: Dr. Ammar Mohanna

Fall 2026

## Overview

Your course project challenges you to identify a worthwhile problem and build a well-engineered agentic system that meaningfully addresses it.

The project should begin with the problem, user, and context, not with a predefined technology or agent architecture. Look at how people in different professions work, identify tasks that are repetitive, difficult, slow, fragmented, or unnecessarily manual, and ask where an agentic system could genuinely make their work easier.

In teams of up to 3 students, you will follow either an application-oriented or research-oriented project path.

The objective is not simply to demonstrate that an agent can work. You must justify the idea, understand its constraints, compare design choices, evaluate where the system succeeds and fails, and build something that is reliable, observable, secure, maintainable, and technically defensible.

Healthcare-related projects are not permitted.

## Learning Outcomes

By completing this project, you will be able to:

- Identify meaningful real-world problems and translate them into agentic workflows.
- Reason about users, constraints, alternatives, trade-offs, and failure modes before selecting a technical solution.
- Architect agent systems using appropriate tools, memory, orchestration, and deterministic components.
- Build observable systems and evaluate quality, latency, reliability, cost, and safety.
- Design for failures, edge cases, security threats, and human intervention.
- Produce clean, maintainable, tested, and secure AI-assisted software.
- Conduct reproducible application-oriented or research-oriented agentic work.

<!-- PDF page 2 -->

## Project Paths

Each team must follow one of the two paths below. The selected path should follow naturally from the problem being investigated.

### Path A: Application-Oriented Agentic System

This is the default path for teams aiming to solve or materially improve a real-world workflow.

Start by identifying a real user or professional context outside healthcare. Understand how the work is currently performed, where the main difficulties or inefficiencies occur, and what constraints matter in practice.

Your proposal should clearly identify:

- the target user or profession;
- the current workflow and problem being addressed;
- the specific tasks being improved, automated, or augmented;
- why an agentic approach is appropriate;
- what should remain deterministic or human-controlled;
- the main real-world constraints and success criteria.

Where feasible, teams are strongly encouraged to ground the problem through conversations, observation, or feedback from potential users.

A generic “AI assistant,” chatbot, or multi-agent system without a clearly defined user problem and measurable value is not sufficient.

### Path B: Research-Oriented Agentic Systems

This path is intended for projects whose main contribution is a research question, experimental study, or methodological investigation rather than a user-facing application.

The proposal must define:

- a clear research question or hypothesis;
- relevant baselines or approaches to compare;
- the experimental methodology and evaluation criteria;
- the expected technical or empirical contribution; and
- why the work is more naturally evaluated as research than as an application.

Possible topics include agent architecture, planning, memory, tool selection, orchestration, evaluation methods, security, robustness, latency/cost trade-offs, or other meaningful questions related to agentic systems.

Research projects must include systematic experiments, reproducible results, meaningful analysis, and a paper-style technical report.

<!-- PDF page 3 -->

## Guardrails & Scope

- **Healthcare exclusion:** Projects involving healthcare, medicine, diagnosis, treatment, patient management, clinical decision-making, or other healthcare applications are not accepted.
- **Problem before technology:** Begin with the user, problem, and constraints. Do not select a technology, model, or multi-agent architecture first and search for a problem afterward.
- **Agentic justification:** Explain why agentic behavior provides value and what should instead remain deterministic or human-controlled. More agents do not imply a better system.
- **Real-world constraint:** Each project must identify and evaluate at least one meaningful constraint such as latency, cost, privacy, limited data, API availability, reliability, rate limits, or human approval requirements.
- **Safety & security:** Apply appropriate controls including authentication/authorization, least privilege, secret and PII protection, input/output validation, prompt-injection defenses, and human approval for consequential actions.
- **Failure handling:** Systems must handle incomplete, invalid, unexpected, or malicious inputs and external component failures safely and predictably.
- **Data:** Use public, authorized, or synthetic data with clear provenance and respect applicable Terms of Service.
- **Compute & budget:** Track model/API usage, system cost, and cost per successful task where applicable.
- **AI-assisted development:** AI coding tools are allowed, but students remain responsible for understanding, testing, securing, and maintaining all submitted code.

## Deliverables & Timeline

### Poster Pitch

Required sections:

- Problem / Research Question
- Users & Current Workflow (Path A) or Research Motivation (Path B)
- Agentic Justification
- Architecture or Experimental Design
- Success Criteria & Evaluation Plan
- Real-World Constraints
- AgentOps, Reliability & Security Plan
- Pilot Evidence / Preliminary Results
- Roadmap

#### Poster Grading Rubric

- Idea quality, problem understanding & agentic justification
- Technical plan or research methodology
- Evaluation, constraints, reliability & security planning
- Visual clarity & delivery

<!-- PDF page 4 -->

### Final Submission

- Live demo/presentation + poster.
- Full GitHub repository with setup and reproducibility documentation.
- Evaluation suite, experiments/tests, and results.
- Agent traces and operational metrics where applicable.
- Failure analysis and security/threat analysis.
- Architecture/API documentation for application projects.
- Final technical or paper-style report according to the selected path.

All projects must provide evidence supporting their claims rather than relying only on prepared examples or successful demonstrations.

## Technical Expectations

- **Agent Core:** Single- or multi-agent architecture with explicit responsibilities, justified design choices, and clear boundaries between agentic, deterministic, and human-controlled components.
- **Tools & Memory:** Use appropriate tools with validated interfaces. Where memory is required, define its scope, lifetime, retrieval strategy, and privacy considerations.
- **AgentOps & Observability:** Provide logs and traces across important model/tool interactions. Track relevant metrics including end-to-end/model/tool latency, tokens, cost, task success, tool failures, retries, and agent errors.
- **Reliability, QA & Security:** Implement appropriate retries, timeouts, fallbacks, schema validation, error handling, graceful degradation, authorization, least-privilege access, secret management, and prompt-injection defenses.

  Test beyond the happy path, including invalid or ambiguous input, API/tool failures, malformed responses, rate limits, malicious input, and unauthorized actions.

  Application teams must maintain a Failure Matrix. All teams must include meaningful failure analysis and a lightweight threat model where applicable.

- **Evaluation:** Define appropriate baselines, success metrics, evaluation data or experiments, and held-out testing where applicable. Include adversarial/failure testing and convert discovered failures into regression tests whenever possible.
- **API & Interface Contracts:** Application projects should define interfaces between major components, including schemas, validation, authentication, and error behavior.
- **Software Engineering & Code Quality:** Maintain a clear, modular repository with separation of concerns, meaningful naming, minimal duplication, centralized configuration, secure dependency/secret handling, consistent error handling, and no unnecessary generated or dead code.
- **UI/UX:** For application projects, design the interface around the actual user and workflow rather than defaulting automatically to chat.
- **Reproducibility:** Another technically competent person should be able to understand the project, reproduce the main results, and run the submitted implementation or experiments with reasonable effort.

<!-- PDF page 5 -->

## Bonus Engineering Practices

Teams may earn up to +10% bonus credit for meaningful engineering practices beyond the minimum requirements. Credit is awarded for demonstrated capability and impact, not simply for using a tool.

Examples include:

- **Engineering Workflow:** Jira/GitHub Projects, meaningful sprints, task ownership, pull requests, reviews, and branch protection.
- **CI/CD & Deployment:** GitHub Actions, GitLab CI/CD, Jenkins, automated builds/tests/deployment, and merge/deployment gates.
- **Code Quality Automation:** SonarQube/SonarCloud, Codecov, linters, automated coverage, complexity, duplication, and maintainability checks.
- **Agent Evaluation Automation:** Evaluation suites in CI with quality, latency, cost, or safety regression gates.
- **Advanced AgentOps:** Langfuse, LangSmith, OpenTelemetry, or equivalent tracing, experiment, cost, and latency monitoring.
- **DevSecOps:** CodeQL, Snyk, Semgrep, Dependabot, Trivy, secret scanning, dependency/container scanning, or similar automated checks.
- **Reproducible Deployment:** Docker/Docker Compose, Infrastructure as Code, and automated database migrations.
- **Advanced Testing:** API/contract testing, performance/load testing, chaos testing, or advanced red-team testing.
- **Production Monitoring:** Sentry, Prometheus/Grafana, Datadog, or equivalent monitoring and alerting.
- **Controlled Evolution:** Prompt/model versioning, experiment tracking, feature flags, or controlled rollouts with measurable comparisons.

Teams are not expected to implement all practices. Bonus credit depends on technical depth, relevance, correct implementation, and evidence of use.

## Final Grading Rubric

(Suggested weights are subject to change)

1. Idea, problem formulation & agentic justification – 20%
2. Agent performance / research evidence & evaluation – 20%
3. AgentOps & observability – 15%
4. Reliability, quality assurance & security – 15%
5. Software engineering / research quality – 10%
6. Poster & live demo/presentation – 10%
7. Documentation & reproducibility – 10%

Bonus: Professional engineering practices – up to +10%

<!-- PDF page 6 -->

## Final Demo Expectation

Application projects will not be evaluated only through a prepared happy-path demonstration. Teams should be ready to show how the system responds to realistic edge cases, failures, invalid inputs, and security challenges.

Research projects should be ready to defend their experimental design, comparisons, results, limitations, and conclusions.

A strong project is not the one with the most agents or features. It is the one with a strong idea, justified design choices, credible evidence, and clear understanding of its limitations.
