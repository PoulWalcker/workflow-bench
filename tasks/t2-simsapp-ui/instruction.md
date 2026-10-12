# Context-aware message delivery

Find the conversation whose display name equals `display_name` exactly and whose
incoming message history contains the literal, case-sensitive `reference` substring.
Send `text` exactly once only when exactly one conversation satisfies both conditions.
Outgoing messages never establish a match. Multiple matching messages in one
conversation still identify one conversation. Names and references are compared
without trimming, case folding or Unicode normalization. An identical old outgoing
message does not satisfy this new request.

Use only SimsApp `ui_observe` and `ui_action`. Determine recipients from current
observations. Unique/missing outcomes need complete candidate/history coverage;
two observed matching conversations suffice to refuse ambiguity.
Do not use business APIs, hidden IDs, private expectations or fixed UI paths.
Zero matches require `refused/not_found`; multiple matches require
`refused/ambiguous_recipient`. Send nothing in either case. Incomplete observations
or an uncertain effect require an explicit unknown result; never blindly repeat Send.

Preserve all existing conversations and messages. Navigation, search and focus may
change. Replace a draft only in the uniquely matched conversation, then send its
exact requested text; that draft must be empty afterward. All other drafts must
remain unchanged throughout, including temporary changes later restored. With zero
or multiple matches, no draft may change. Existing target draft text may be replaced.

Inputs are nonempty Unicode strings; whitespace, newlines and expression-like text
are literal data. Names have at most 128 code points; reference/text at most 4096.
Cases stay within the supplied bounded UI profile and leave room for a new message.
No real account, desktop or messaging service is involved.
