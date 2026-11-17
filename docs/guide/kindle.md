# Send chapters to a Kindle

<script setup>
import { release } from '../.vitepress/release'
</script>

MeManga can email each downloaded chapter to a Kindle through Amazon's Send
to Kindle service. This page covers the setup, what is sent and when, and
what to check when a chapter does not arrive.

Sections that apply only to the development version say so. Everything else
is the same in {{ release.tag }}.

## What you need

| | What it is |
|---|---|
| A Send to Kindle address | The address Amazon gives each Kindle device and app, ending in `@kindle.com`. Chapters are sent **to** it. |
| A sender email account | An email account of yours with SMTP access. Chapters are sent **from** it. |
| The sender account's password | The password MeManga signs in to that account with. For Gmail this is a Google app password, not your normal password: see [Gmail app passwords](#gmail-app-passwords). |
| PDF or EPUB output | Amazon accepts PDF and EPUB by email. CBZ, ZIP and image folders are not sent. |

MeManga does not use your Amazon password and does not sign in to Amazon.

The development version checks the format and does not send anything else.
{{ release.tag }} does not check it, so choose PDF or EPUB yourself.

### Gmail app passwords

MeManga signs in to the sender account with a password. A Gmail account
needs a Google app password for this. According to
[Google's help page on app passwords](https://support.google.com/mail/answer/185833):

- You need 2-Step Verification turned on in your Google Account before you
  can create an app password.
- The option can be missing when 2-Step Verification is set up only for
  security keys, when the account belongs to a work, school or other
  organization, or when the account has Advanced Protection.
- Google revokes app passwords when you change your Google Account
  password. You then need a new one.

For any other provider, follow that provider's instructions for signing in
to SMTP from a program.

## Step 1: approve your sender address at Amazon

Amazon only delivers documents from addresses you have approved.

1. Sign in to Amazon and open **Manage Your Content and Devices**.
2. Open **Preferences** and scroll to **Personal Document Settings**.
3. Under **Approved Personal Document E-mail List**, add the sender address
   you will use.
4. On the same page, note your **Send to Kindle** address for the device or
   app you want to read on.

Amazon describes the service and its requirements in
[Learn How to Use Your Send to Kindle Email Address](https://www.amazon.com/gp/help/customer/display.html?nodeId=G7NECT4B4ZWHQ8WV).
The names of Amazon's menus can differ by country and may change. If the
steps above do not match what you see, search Amazon's help for "Send to
Kindle".

## Step 2: enter the settings

### In the desktop app

1. Open **Settings → General** and set **Delivery Mode** to
   **Email (send to Kindle)**. Set **Output Format** to PDF or EPUB.
2. Open **Settings → Kindle / Email** and fill in:

| Field | Value |
|---|---|
| Kindle Email | Your Send to Kindle address |
| Sender Email | The approved sender address |
| SMTP Server | Your email provider's SMTP server. The default is `smtp.gmail.com`. |
| SMTP Port | The default is `587`. |
| App Password | The password for the sender account (for Gmail, the app password) |

3. Choose **Save settings**.

### On the command line

Run `memanga config` and answer the questions about delivery and email.

In the development version you can also set values one at a time:

```sh
memanga config set delivery.mode email
memanga config set delivery.output_format pdf
memanga config set email.kindle_email "YOUR-KINDLE-ADDRESS"
memanga config set email.sender_email "YOUR-SENDER-ADDRESS"
memanga config set email.app_password
```

Replace the two placeholders with your own addresses. The last command asks
for the password without showing it. `memanga config email` shows the email
settings with the password masked.

## Step 3: test it

In the development version there are two tests. Both use the network.

**Sign-in only.** Signs in to the mail server and sends nothing. In the
desktop app choose **Check Login**. On the command line:

```sh
memanga config email --test
```

**Test document.** Emails a one-page PDF named `MeManga-test.pdf`, with the
subject "MeManga test document", to your Kindle address. In the desktop app
choose **Send Test PDF**. On the command line:

```sh
memanga config email --send-test
```

A test that succeeds means your mail server accepted the email. It does not
prove that it reached your Kindle: Amazon delivers it only when the sender is
approved. Check your Kindle library for the test document. If it does not
appear, see [When a chapter does not arrive](#when-a-chapter-does-not-arrive).

{{ release.tag }} has one button, **Test Connection**, which signs in only.

## What is sent, and when

When delivery mode is Email, a chapter is sent right after it is downloaded.
There is nothing to do by hand.

### Which series are sent

Each series has a **Send to Kindle after download** switch on its page.

In the development version, **Settings → General → Send to Kindle** also
decides what happens to series you have not set either way:

| Choice | Effect |
|---|---|
| Only manga I choose | A series is sent only when its switch is on. |
| Every manga in my library | Every series is sent unless its switch is off. |

On the command line the same choice is `email.kindle_scope` (`selected` or
`all`), and `memanga edit "TITLE" --kindle` or `--no-kindle` sets the switch
of one series.

### Keeping or deleting the file

By default the chapter stays in your download folder after it is sent. With
**Delete file after sending** turned on, the file is removed once it has
been sent, and only then.

### Email subject

The subject of each email is the chapter's file name without its extension.
With the default file naming this looks like `Some Title - Chapter 12`.

There is no setting to change the subject, and MeManga adds nothing to it
apart from the part numbers described below. It does not add a conversion
request such as `convert`, and it does not ask Amazon to convert a file in
any other way. What Amazon does with a PDF or EPUB after it arrives is
decided by Amazon.

### Large chapters are split

Email providers limit the size of an email, and attachments grow by about a
third when they are encoded for email. MeManga therefore keeps each file
under a safe size.

- **PDF:** a chapter that is too large is split into several PDFs, each sent
  in its own email. The parts are numbered at the end of the subject and of
  the file name: `Some Title - Chapter 12.01`, `Some Title - Chapter 12.02`,
  and so on. They arrive on your Kindle as separate documents.
- **EPUB:** an EPUB cannot be split. One that is too large is not sent, and
  MeManga tells you to use PDF instead.

In {{ release.tag }} the limit is fixed: a file may be at most 18 MB before
encoding. In the development version it follows the setting
`email.max_email_mb`, the size limit of your email provider in megabytes,
from 10 to 50, with 25 as the default. A file may use 72% of it, which is 18
MB at the default.

Amazon's own limit for one email to a Send to Kindle address is 50 MB in
total, according to its help page linked above.

## Switch back to local downloads

To stop sending chapters and only save them to your download folder:

- **In the desktop app:** open **Settings → General**, set
  **Delivery Mode** to **Local (save to disk)** and choose
  **Save settings**.
- **On the command line:** run `memanga config`, answer `1` (local) to the
  delivery mode question and confirm the download folder.
  <Badge type="info" :text="`Not in ${release.tag}`" /> You can also run:

  ```sh
  memanga config set delivery.mode local
  ```

From then on, chapters are saved to the download folder and are not
emailed, whatever the switch of their series says. Chapters already waiting
in the desktop app's download queue, and a check that is already running on
the command line, keep the setting they started with.

Switching does not delete anything:

- The email settings and the saved app password stay as they are.
- Each series keeps its **Send to Kindle after download** switch, and the
  Send to Kindle choice stays too. They apply again when you choose **Email
  (send to Kindle)** later.
- In the development version, chapters that were not sent stay listed.
  While delivery is local, `memanga send` and `memanga send --pending`
  stop with "Kindle delivery is not set up", and the desktop app's **Send**
  button asks you to turn on Kindle email delivery first.
  `memanga send --pending --clear` forgets these chapters; the files stay on
  disk.

The tests in [step 3](#step-3-test-it) still sign in, and send a test
document, with the saved settings.

## Where the password is stored

MeManga stores the password in your system's keyring when one is available,
for example the macOS Keychain or the Windows Credential Locker. Whether a
keyring is available depends on your system and how it is set up.
If no keyring can be used, the password is saved as plain text in
`config.yaml`. Keep that file private. The development version tells you
when this happens; {{ release.tag }} does not.

In the development version you can supply the password from outside instead,
which suits servers and containers. Set one of these environment variables,
not both:

- `MEMANGA_SMTP_PASSWORD`: the password itself.
- `MEMANGA_SMTP_PASSWORD_FILE`: the path of a file that contains only the
  password.

A password supplied this way is used instead of the stored one and is never
written to disk by MeManga.

## Other email providers

The default settings are for Gmail. For another provider, enter its SMTP
server and port.

In {{ release.tag }} the connection always starts unencrypted and is
upgraded with STARTTLS. There is no setting for this.

In the development version, `email.smtp_tls` chooses how the connection is
secured:

| Value | Meaning |
|---|---|
| `auto` (default) | Port 465 is encrypted from the start; any other port uses STARTTLS. |
| `starttls` | Always upgrade with STARTTLS. |
| `implicit` | Always encrypt from the start. |

`email.smtp_timeout` sets how many seconds each step may take. The default
is 60.

## When a chapter does not arrive

Work through these in order.

1. **Is the output format PDF or EPUB?** See
   [What you need](#what-you-need).
2. **Does sign-in work?** Use the sign-in test in step 3. If it fails, check
   the server, the port and the password. With Gmail, check that the app
   password still exists: see [Gmail app passwords](#gmail-app-passwords).
3. **Is the sender approved at Amazon?** Open the approved list from step 1
   and check that it contains the sender address exactly as you entered it
   in MeManga. Also look in the sender account's mailbox for any message
   about the email.
4. **Is the Kindle address right?** Compare it with the address shown at
   Amazon for the device or app you read on.
5. **Was the chapter too large?** A large EPUB is not sent. Switch to PDF.
6. **Is the device online?** Amazon's help page lists an internet connection
   among the requirements, and says Amazon keeps trying to deliver a
   document for up to 60 days.

In the development version, a chapter that was downloaded but could not be
emailed is remembered:

- In the desktop app, its row says **Not sent to Kindle** and has a **Send**
  button. The reason is in **Notifications**.
- On the command line, `memanga send --pending --list` shows these chapters
  and `memanga send --pending` sends them again.

To send a chapter that is already downloaded again, use
`memanga send "TITLE" CHAPTER`, for example `memanga send "TITLE" 12`.
Replace `TITLE` with the name of the series.
