"""Email sharing (scripts/send.py): attachments built from the record, SMTP wiring,
validation, and the audit trail. SMTP is mocked: no network, no credentials."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from edu_kit import audit
from edu_kit.case_record import CaseRecord
from scripts.send import SendError, attachment, main, recipients, send_run, smtp_config
from tests.test_documents import DocumentsBase

CONFIG = {
    "host": "smtp.example.com",
    "port": 587,
    "user": "teacher",
    "password": "s3cret",
    "sender": "agent@school.edu",
    "tls": True,
}


def servers(mock_smtp):
    mock_smtp.return_value.__enter__.return_value = mock_smtp.return_value
    return mock_smtp.return_value


class SendTest(DocumentsBase):
    def test_dry_run_builds_without_connecting(self):
        self.filed_scheme()
        with mock.patch("smtplib.SMTP") as smtp, mock.patch("smtplib.SMTP_SSL") as ssl:
            result = send_run(
                self.root, self.run_id, "scheme", "pdf", ["t@e.co"], dry_run=True, config=CONFIG
            )
        smtp.assert_not_called()
        ssl.assert_not_called()
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["file"], f"{self.run_id}-scheme.pdf")
        self.assertGreater(result["bytes"], 500)
        shared = [e for e in audit.read(self.root, self.run_id) if e["event"] == "document_shared"]
        self.assertEqual(shared, [])

    def test_attachment_is_a_real_export(self):
        self.filed_scheme()
        title, filename, data = attachment(self.root, self.run_id, "scheme", "pdf")
        self.assertTrue(data.startswith(b"%PDF-1.4"))
        self.assertTrue(filename.endswith("-scheme.pdf"))
        self.assertIn("Scheme", title)
        _, _, docx = attachment(self.root, self.run_id, "scheme", "docx")
        self.assertTrue(docx.startswith(b"PK"))

    def test_send_connects_starttls_login_and_attaches(self):
        self.filed_scheme()
        with mock.patch("smtplib.SMTP") as smtp_cls:
            server = servers(smtp_cls)
            result = send_run(
                self.root, self.run_id, "scheme", "pdf", ["a@b.co", "c@d.co"],
                subject="S", message="M", config=CONFIG,
            )
        smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=30)
        server.starttls.assert_called_once_with()
        server.login.assert_called_once_with("teacher", "s3cret")
        email = server.send_message.call_args[0][0]
        self.assertEqual(email["To"], "a@b.co, c@d.co")
        self.assertEqual(email["From"], "agent@school.edu")
        self.assertEqual(email["Subject"], "S")
        parts = [p for p in email.iter_attachments()]
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].get_filename(), result["file"])
        self.assertTrue(parts[0].get_content().startswith(b"%PDF-1.4"))
        events = audit.read(self.root, self.run_id)
        self.assertEqual(events[-1]["event"], "document_shared")
        self.assertEqual(events[-1]["detail"]["to"], ["a@b.co", "c@d.co"])
        self.assertNotIn("s3cret", json.dumps(result))

    def test_port_465_uses_ssl_without_starttls(self):
        self.filed_scheme()
        config = dict(CONFIG, port=465)
        with mock.patch("smtplib.SMTP") as smtp, mock.patch("smtplib.SMTP_SSL") as ssl:
            server = servers(ssl)
            send_run(self.root, self.run_id, "scheme", "pdf", ["a@b.co"], config=config)
        smtp.assert_not_called()
        ssl.assert_called_once_with("smtp.example.com", 465, timeout=30)
        server.starttls.assert_not_called()

    def test_tls_off_skips_starttls(self):
        self.filed_scheme()
        config = dict(CONFIG, tls=False, user="")
        with mock.patch("smtplib.SMTP") as smtp_cls:
            server = servers(smtp_cls)
            send_run(self.root, self.run_id, "scheme", "pdf", ["a@b.co"], config=config)
        server.starttls.assert_not_called()
        server.login.assert_not_called()

    def test_smtp_failures_are_reported_without_credentials(self):
        self.filed_scheme()
        import smtplib

        with mock.patch("smtplib.SMTP") as smtp_cls:
            servers(smtp_cls).send_message.side_effect = smtplib.SMTPException("refused")
            with self.assertRaises(SendError) as failure:
                send_run(self.root, self.run_id, "scheme", "pdf", ["a@b.co"], config=CONFIG)
        self.assertIn("could not send", str(failure.exception))
        self.assertNotIn("s3cret", str(failure.exception))

    def test_recipients_and_config_validation(self):
        self.assertEqual(recipients("a@b.co, c@d.co"), ["a@b.co", "c@d.co"])
        for bad in ("", "not-an-address", "a@b.co," * 11):
            with self.assertRaises(SendError):
                recipients(bad)
        with self.assertRaisesRegex(SendError, "SMTP_HOST"):
            smtp_config({"SMTP_FROM": "a@b.co"})
        with self.assertRaisesRegex(SendError, "SMTP_FROM"):
            smtp_config({"SMTP_HOST": "h"})
        with self.assertRaisesRegex(SendError, "SMTP_PORT"):
            smtp_config({"SMTP_HOST": "h", "SMTP_FROM": "a@b.co", "SMTP_PORT": "x"})
        self.assertEqual(smtp_config({"SMTP_HOST": "h", "SMTP_FROM": "a@b.co"})["port"], 587)

    def test_attachment_errors_name_the_problem(self):
        with self.assertRaisesRegex(SendError, "no case record"):
            send_run(self.root, "run-missing", "scheme", "pdf", ["a@b.co"], dry_run=True)
        with self.assertRaisesRegex(SendError, "no case record"):
            send_run(self.root, self.run_id, "scheme", "pdf", ["a@b.co"], dry_run=True)
        CaseRecord(self.root, self.run_id)
        with self.assertRaisesRegex(SendError, "no filed document"):
            send_run(self.root, self.run_id, "scheme", "pdf", ["a@b.co"], dry_run=True)
        with self.assertRaisesRegex(SendError, "one of"):
            attachment(self.root, self.run_id, "syllabus", "pdf")
        with self.assertRaisesRegex(SendError, r"one of pdf, docx"):
            attachment(self.root, self.run_id, "scheme", "txt")

    def test_main_exit_codes_without_touching_anything(self):
        with self.assertRaises(SystemExit):
            main(["run-x", "--what", "scheme"])
        self.assertEqual(
            main(["run-missing", "--what", "scheme", "--format", "pdf", "--to", "a@b.co", "--dry-run"]),
            1,
        )


if __name__ == "__main__":
    unittest.main()
