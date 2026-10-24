package probe;

import static probe.Facts.describe;
import static probe.Facts.fact;
import static probe.jooq.Tables.DOCUMENTS;

import java.util.Arrays;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import org.jooq.DSLContext;
import org.jooq.impl.CallbackExecuteListener;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.simple.JdbcClient;
import probe.app.Note;
import probe.app.NoteRepository;
import probe.app.ProbeApplication;

@SpringBootTest(classes = ProbeApplication.class)
class OptimisticLockingTest {

    @Autowired DSLContext dsl;
    @Autowired JdbcClient jdbc;
    @Autowired NoteRepository notes;

    @Test
    void jooqRecordVersionWithAndWithoutTheSetting() {
        for (boolean optimistic : new boolean[] {true, false}) {
            jdbc.sql("DELETE FROM documents").update();
            jdbc.sql("INSERT INTO documents (id, title, version) VALUES (1, 'start', 0)").update();
            List<String> sql = new CopyOnWriteArrayList<>();
            DSLContext ctx = dsl.configuration()
                    .deriveSettings(s -> s.withExecuteWithOptimisticLocking(optimistic))
                    .deriveAppending(new CallbackExecuteListener().onExecuteStart(c -> sql.add(c.sql())))
                    .dsl();
            fact("jooq-listeners optimistic=" + optimistic, Arrays.stream(ctx.configuration().executeListenerProviders())
                    .map(provider -> provider.provide().getClass().getSimpleName()).toList().toString());
            var first = ctx.fetchOne(DOCUMENTS, DOCUMENTS.ID.eq(1L));
            var second = ctx.fetchOne(DOCUMENTS, DOCUMENTS.ID.eq(1L));
            first.setTitle("first");
            sql.clear();
            first.store();
            fact("jooq-store-sql optimistic=" + optimistic, String.join(" ;; ", sql));
            second.setTitle("second");
            try {
                second.store();
                fact("jooq-stale-store optimistic=" + optimistic, "stored without error");
            } catch (RuntimeException e) {
                fact("jooq-stale-store optimistic=" + optimistic, describe(e));
            }
            var row = jdbc.sql("SELECT title || ' at version ' || version FROM documents WHERE id = 1")
                    .query(String.class).single();
            fact("jooq-row-after optimistic=" + optimistic, row);
        }
    }

    @Test
    void springDataJdbcVersion() {
        notes.deleteAll();
        Note saved = notes.save(new Note(null, "start", null));
        Note first = notes.findById(saved.id()).orElseThrow();
        Note second = notes.findById(saved.id()).orElseThrow();
        fact("spring-data-jdbc-version", "inserted at version " + saved.version());
        notes.save(first.withBody("first"));
        try {
            notes.save(second.withBody("second"));
            fact("spring-data-jdbc-stale-save", "saved without error");
        } catch (RuntimeException e) {
            fact("spring-data-jdbc-stale-save", describe(e));
        }
        fact("spring-data-jdbc-row-after", notes.findById(saved.id()).orElseThrow().toString());
    }
}
