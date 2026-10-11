# Stage I — submission readiness

Checked **2026-10-11** against the [organizer's contest site](https://contest.bhuntr.com/tw/39jg9vimiynrhlksze/home/)
and [ASUS-published listing](https://bhuntr.com/tw/competitions/39jg9vimiynrhlksze).
The site displays **2026-10-14 17:00, Asia/Taipei**. Its current announcements take precedence over this checklist.

## Required for Stage I

- English proposal deck: at most **20 main pages**; appendices excluded. Cover the problem, solution and methods,
  hardware/software design, expected outcomes, references and the GitHub source link.
- Working demo video with primarily English explanation, **recommended within 3 minutes**, uploaded to
  **YouTube as unlisted**, with its URL supplied at submission.
- Select one theme, one hardware track and one participation format. VESTIGE targets **Workplace AI / Battlefield
  Lightning / UGen300**; the entrant must confirm Global Online versus Onsite in the form.

**Stage I permits validation on a laptop, SBC or VM.** Required use of the selected hardware/environment starts
in Stage II. Do not describe laptop runs or vendor benchmarks as UGen300 measurements.

## README: requirement versus preparation

Section VI(1) does not prescribe a separate Stage I README format or page count. It asks for the GitHub link
in the deck. Section VI(2), for the Global Online final, explicitly lists a repository with architecture,
README, model information and performance validation. Section VI(3) says Onsite technical review may inspect
README completeness and hardware integration.

Our recommendation is to provide those materials now so reviewers can understand and reproduce the prototype.
This is preparation, not an additional invented Stage I requirement.

## Repository readiness

- [x] English [README](../README.md) with product explanation, runnable setup and a command-line demo.
- [x] Architecture, current versus planned hardware roles, [model/port notes](hailo_port.md).
- [x] [Feature status](STATUS.md), measured reports and [reproduction commands](REPRODUCING.md).
- [x] Public-footage attribution and staged/synthetic-data disclosures.
- [ ] Export the final **VESTIGE** English deck and check page count, references, screenshots and product names.
  [deck2/](../deck2/) contains the VESTIGE slide sources, not yet a verified final submission PDF.
- [ ] Record a matching English walkthrough, upload as unlisted, and put the verified URL near the README top.
  [video/youtube.txt](../video/youtube.txt) is draft upload metadata, not a published video URL.
- [ ] Confirm theme, track, participation format and team information in the entry form.
- [ ] Test deck/GitHub/video access from a signed-out browser, submit, and retain the receipt.
  A repository commit is not proof of contest submission.

## Recommended demo sequence

| Time | Screen | Point to demonstrate |
|---|---|---|
| 0:00–0:20 | Home | The operator's problem and the question VESTIGE answers. |
| 0:20–1:15 | Campus answer | Direct conclusion → citation opens video → inferred links → coverage ends. |
| 1:15–1:50 | Metro or construction event | Why the alert exists, its source evidence and a human review. |
| 1:50–2:35 | IncidentLab | Real stress-test output, a frame comparison and the retention/latency trade-off. |
| 2:35–3:00 | Architecture/status | Laptop prototype today; UGen300 measurement plan for Stage II. |

This sequence is our proposal, not an organizer-prescribed script. Capture the actual UI and label the footage
and staged inputs; do not imply that the site is connected to real campus or metro CCTV.

## Judging and other conditions

The organizer assigns innovation **30%**, business potential/feasibility **35%**, practical value **25%**,
and storytelling/presentation **10%** (section VII). Demonstrating reproducibility and hardware feasibility
therefore matters alongside the visual presentation.

Sections IX–XI also cover originality, rights to code/models/media, submission and winner usage permissions.
Review those terms in the source before submission. In particular, the originality clause concerns prior
public presentation; the site also requests a GitHub link. This checklist does not determine how the organizer
interprets that clause for development repositories. No entry or agreement has been submitted by this change.

## Verification notes

The primary contest pages were readable in a browser even though the text-fetch service returned a 404.
University reposts corroborate the deck and video requirements:
[NTU](https://www.me.ntu.edu.tw/web/news/news_in.jsp?np_id=NP1788935588614),
[NTHU](https://dcs.site.nthu.edu.tw/p/406-1174-314043,r63.php).
The previously supplied NTU COOL reference-PDF links could not be retrieved during this check; requirements
above come from the current organizer pages, not an inferred reading of those PDFs.
