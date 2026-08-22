# Monetisation

[Русская версия](MONETIZATION.md)

The system earns from **the author's own projects**, not from third-party
advertising. There are no external ads inside Radar and none are planned.

## What is free, always

Danger alerts, utility outages, weather, SOS and the event history are free
and do not depend on any subscription. This is the point of the system:
a warning that only reaches paying users is not a warning system.

## One subscription

Technically there are two paid parts — news digests and unlimited video
downloads — but they are sold as one. Paying for either opens both, the
term is the longer of the two, and extending one never shortens the other.

The reason is simple: for a person this is a single purchase. Charging
twice for the same feeling is a fast way to lose trust.

| What | Free | Paid |
|---|---|---|
| Danger alerts, utilities, weather, SOS | always | — |
| Event history | always | — |
| News digests | 1 topic of 18 | all topics |
| Video download | 20 per day, 50 MB each | no daily limit, 50 MB each |

Price: **10 Telegram Stars for 30 days.**

The 50 MB cap is not lifted by the subscription. It is a Telegram Bot API
limit, not our decision, and the purchase description says so plainly —
promising what you cannot deliver is worse than not selling it.

## Staff access

Administrators get everything without paying. Otherwise a bug in the paid
part would be found first by someone who paid for it, not by the developer.

Staff access is not stored in the database: it is derived from the role on
every request, so demoting a role closes access immediately rather than
leaving an open subscription behind.

## Partner projects

A section listing the author's own projects, with promo codes. One code
per person per project — pressing again returns the same code, not a new
one. Otherwise the issuing turns into an endless source of codes and the
partner rightly stops accepting them.

The export handed to a partner contains only the code and the issue date.
No user identifiers, and none can be derived from the code — it is random,
not computed from the account. That is a promise, not a formatting detail.

## What is deliberately not monetised

**Link shortening.** Bitly and a dozen others do it free and unlimited;
selling limits where a competitor gives none is not a business. A public
shortener is also bait for phishing, and the domain pays for it — together
with everything else hosted on it, including links inside danger alerts.
