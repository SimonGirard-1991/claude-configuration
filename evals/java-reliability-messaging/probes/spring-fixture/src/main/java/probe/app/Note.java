package probe.app;

import org.springframework.data.annotation.Id;
import org.springframework.data.annotation.Version;
import org.springframework.data.relational.core.mapping.Table;

@Table("notes")
public record Note(@Id Long id, String body, @Version Long version) {

    public Note withBody(String newBody) {
        return new Note(id, newBody, version);
    }
}
