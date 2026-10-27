// DraveAgenda - Copyright (C) 2026 Dravenlock (Roger & Claudio). Vrije software onder de GNU GPL v3.0.
// Wekker: laat op het goede moment een herinnering zien, ook als de app dicht is.
// Na het opnieuw opstarten van de telefoon zet hij de herinneringen weer klaar (uit files/wekkers.txt).
package nl.dravenlock.draveagenda;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;

public class Wekker extends BroadcastReceiver {
    public static final String KANAAL = "draveagenda_herinneringen";

    @Override
    public void onReceive(Context ctx, Intent intent) {
        String actie = intent.getAction();
        if (Intent.ACTION_BOOT_COMPLETED.equals(actie) || "android.intent.action.MY_PACKAGE_REPLACED".equals(actie)) {
            herplan(ctx);
            return;
        }
        toon(ctx, intent.getIntExtra("nr", 0), intent.getStringExtra("titel"), intent.getStringExtra("tekst"));
    }

    public static void kanaal(Context ctx) {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
            NotificationChannel ch = new NotificationChannel(KANAAL, "Herinneringen", NotificationManager.IMPORTANCE_HIGH);
            ch.setDescription("Herinneringen voor je afspraken");
            ch.enableVibration(true);
            nm.createNotificationChannel(ch);
        }
    }

    public static void toon(Context ctx, int nr, String titel, String tekst) {
        kanaal(ctx);
        NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
        Intent open = ctx.getPackageManager().getLaunchIntentForPackage(ctx.getPackageName());
        int vlag = PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0);
        PendingIntent pi = PendingIntent.getActivity(ctx, 9000 + nr, open, vlag);
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(ctx, KANAAL) : new Notification.Builder(ctx);
        b.setSmallIcon(ctx.getApplicationInfo().icon)
         .setContentTitle(titel == null ? "DraveAgenda" : titel)
         .setContentText(tekst == null ? "" : tekst)
         .setStyle(new Notification.BigTextStyle().bigText(tekst == null ? "" : tekst))
         .setAutoCancel(true)
         .setContentIntent(pi);
        if (Build.VERSION.SDK_INT < 26) {
            b.setPriority(Notification.PRIORITY_HIGH).setDefaults(Notification.DEFAULT_ALL);
        }
        nm.notify(5000 + nr, b.build());
    }

    public static void zet(Context ctx, int nr, long wanneer, String titel, String tekst) {
        AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        Intent i = new Intent(ctx, Wekker.class);
        i.setAction("nl.dravenlock.draveagenda.HERINNER");
        i.putExtra("nr", nr);
        i.putExtra("titel", titel);
        i.putExtra("tekst", tekst);
        int vlag = PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0);
        PendingIntent pi = PendingIntent.getBroadcast(ctx, nr, i, vlag);
        boolean precies = Build.VERSION.SDK_INT < 31 || am.canScheduleExactAlarms();
        if (Build.VERSION.SDK_INT >= 23) {
            if (precies) am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, wanneer, pi);
            else am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, wanneer, pi);
        } else {
            am.setExact(AlarmManager.RTC_WAKEUP, wanneer, pi);
        }
    }

    public static void weg(Context ctx, int nr) {
        AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        Intent i = new Intent(ctx, Wekker.class);
        i.setAction("nl.dravenlock.draveagenda.HERINNER");
        int vlag = PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0);
        am.cancel(PendingIntent.getBroadcast(ctx, nr, i, vlag));
    }

    // regels in wekkers.txt:  millis<TAB>titel<TAB>tekst
    public static void herplan(Context ctx) {
        try {
            File f = new File(ctx.getFilesDir(), "DraveAgenda-data/wekkers.txt");
            if (!f.exists()) return;
            BufferedReader r = new BufferedReader(new FileReader(f));
            String regel;
            int nr = 0;
            long nu = System.currentTimeMillis();
            while ((regel = r.readLine()) != null) {
                String[] d = regel.split("\t", 3);
                if (d.length < 3) continue;
                long t = Long.parseLong(d[0]);
                if (t > nu) zet(ctx, nr, t, d[1], d[2]);
                nr++;
            }
            r.close();
        } catch (Exception e) {
            // niets aan te doen; bij het openen van de app wordt alles opnieuw klaargezet
        }
    }
}
