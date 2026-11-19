#Definition tips
The definition is what the AI reads to play the character. A few habits make it much more reliable.

    • Keep it concise. Longer definitions can dilute important details and make models less consistent.
    • Always use {{char}} and {{user}} instead of fixed names. They automatically use the current in-chat names.
    • Describe behavior, not just adjectives. Explain how traits actually affect the character.
    • State the character's age explicitly. This reduces ambiguity and can help avoid unnecessary moderation, especially for adult characters.
    • Avoid W++ and pseudo-code. Modern models work best with clear natural language.

❌ Bad

Alice, 22.
Personality("shy" + "loyal" + "sarcastic")
Alice really likes John.

✅ Better

{{char}} is 22 years old.

{{char}} is reserved around strangers and hides her discomfort behind dry jokes. Once she trusts someone, she becomes fiercely loyal and protective.

{{char}} has grown close to {{user}}, but struggles to openly admit how much she relies on them.

#Writing your first message
Your first message sets the opening scene of the chat. ✨

You can use Markdown to format it:
**bold**
→ bold
*italic*
→ italic

We recommend using SillyTavern macros instead of writing names directly:
{{user}}
→ the user's name
{{char}}
→ the character's name

To insert an image, use Markdown image syntax:
![description](https://example.com/image.png)

We recommend uploading images to catbox.moe and pasting the direct image URL here.

Example:

*{{char}} looks up at {{user}}.* "You're finally here."

![Room](https://files.catbox.moe/example.png)

#Character Card mandatory fields
• Display name: Name must be at least 3 characters long. Maximum 80 characters.
• In-chat name: In-Chat Name must be at least 1 characters long. Maximum 50 characters.
• Tagline: Subtitle/Tagline must be at least 10 characters long. Maximum 150 characters.
• Public description: Page Description must be at least 10 characters long. Maximum 25K characters.
• Definition: Character Info must be at least 200 characters long. Aim to 3,5K-6K characters.
• Greeting: First Message must be at least 10 characters long. Am 800–3.2K characters.
• Tags: You must have at least 1 tag. Maximum 100 tags.
• Portrait (Creator will upload by himself manually).
#Character Card optional fields
• Lorebook. Maximum 200 entries. Scan depth 0-100. (Can be imported via json file)
#Character Card LEGACY fields(NOT RECOMMENDED! These legacy fields eat into the token budget, are injected in a fixed order, and degrade results with modern models. Put everything in the Definition instead. Kept only for SillyTavern compatibility.)
• Personality
• Scenario
• Example dialog
• Post-history instructions


#Creator instructions
• Language:
• • Character Card must be in English
• • RP-Chat must be in Russian
• Prohibited themes:
No Sexualization of Minors
Zero tolerance. What counts is how the character is presented, not the stated age.
Counts as underage
    Looks like a child or young teen
    No stated age, but clearly coded under 18
    A scenario that implies underage, like a high school setting
    A user persona implied or intended to be a minor
Counts as adult
    Clearly presented as a young adult
    Adult-coded anime characters without juvenile framing
    Visuals and writing that consistently read as 18+
Never with underage or underage-appearing characters
  Sexual, erotic, or explicit content
  Romantic or flirtatious framing meant to sexualize
  Suggestive outfits, poses, or descriptions
  Sexual chat generation
Good to know
  User persona: the user counts as a character too. Cards where the user is implied or intended to be underage in a sexual or romantic context are prohibited, even if every other character is an adult.
  Side characters: underage side characters may appear in otherwise adult stories, but only if they are never sexualized. A minor as the focus of explicit content makes the card prohibited.
  Youth warning: mandatory for underage-appearing characters, even when the card is wholesome and fully SFW.

No Malicious Content
Cards are for chatting, not for tricking people.
Prohibited
    Scam or phishing links
    Malware or deceptive download links
    Tricking users into revealing personal or payment information
    Impersonating Character Tavern staff or system messages

No Spam
Cards must be usable, coherent, and made for chat, not for testing, advertising, or flooding the catalog.
May be treated as spam
    Fewer than 300 tokens, roughly 1200 characters, in the Definition field. Greetings, lorebook entries, and other fields do not count toward it, however long they are
    Keyboard mashing or placeholder text like "test", "coming soon", or "Stolen from X"
    Mostly ASCII art, URLs, or symbols with little actual character content
    Nonsense or incoherent character names
    Blank, placeholder, or unusably low-quality profile images
    Duplicate public uploads that are not clearly forks or translations
    Announcement-only or information-only cards not meant for chat
