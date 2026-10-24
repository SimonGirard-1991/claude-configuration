package probe.app;

import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

public class Attempts {

    public final List<String> log = new CopyOnWriteArrayList<>();
    public volatile Runnable afterFirstRead = () -> { };

    void runHookOnce() {
        Runnable hook = afterFirstRead;
        afterFirstRead = () -> { };
        hook.run();
    }
}
