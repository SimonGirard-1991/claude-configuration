package probe;

import static probe.Facts.fact;

import jakarta.validation.Validation;
import jakarta.validation.constraints.Email;
import org.hibernate.validator.HibernateValidator;
import org.junit.jupiter.api.Test;

class EmailLengthTest {

    record Holder(@Email String email) {
    }

    @Test
    void emailConstraintBoundsTheLength() {
        var validator = Validation.buildDefaultValidatorFactory().getValidator();
        String label = "b".repeat(63);
        String[] emails = {
            "a".repeat(64) + "@example.com",
            "a".repeat(65) + "@example.com",
            "a".repeat(64) + "@" + String.join(".", label, label, label) + ".com",
            "a".repeat(64) + "@" + String.join(".", label, label, label, label) + ".com",
        };
        for (String email : emails) {
            fact("email-length " + HibernateValidator.class.getPackage().getImplementationVersion(),
                    "@Email on " + email.length() + " characters (local part " + email.indexOf('@') + "): valid="
                            + validator.validate(new Holder(email)).isEmpty());
        }
    }
}
