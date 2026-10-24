package probe.overlap;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(name = "probe.overlap.job", havingValue = "fixed-rate")
public class FixedRateJob {

    @Scheduled(fixedRate = 1000)
    public void run() throws InterruptedException {
        RunCounter.runFor(2500);
    }
}
