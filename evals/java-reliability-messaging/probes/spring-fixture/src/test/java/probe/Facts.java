package probe;

import java.sql.SQLException;

final class Facts {

    private Facts() {
    }

    static void fact(String id, String text) {
        System.out.println("FACT | " + id + " | " + text);
    }

    static String describe(Throwable e) {
        StringBuilder chain = new StringBuilder(e.getClass().getName());
        for (Class<?> c = e.getClass().getSuperclass(); c != null && c != RuntimeException.class && c != Object.class;
                c = c.getSuperclass()) {
            chain.append(" < ").append(c.getSimpleName());
        }
        for (Throwable t = e; t != null; t = t.getCause()) {
            if (t instanceof SQLException s) {
                chain.append(" [SQLSTATE ").append(s.getSQLState()).append("]");
                break;
            }
        }
        return chain.toString();
    }
}
