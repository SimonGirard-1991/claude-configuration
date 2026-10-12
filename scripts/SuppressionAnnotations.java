import com.sun.source.tree.AnnotationTree;
import com.sun.source.tree.CompilationUnitTree;
import com.sun.source.tree.IdentifierTree;
import com.sun.source.tree.MemberSelectTree;
import com.sun.source.tree.Tree;
import com.sun.source.util.JavacTask;
import com.sun.source.util.SourcePositions;
import com.sun.source.util.TreeScanner;
import com.sun.source.util.Trees;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Locale;
import java.util.StringJoiner;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.tools.JavaCompiler;
import javax.tools.JavaFileObject;
import javax.tools.StandardJavaFileManager;
import javax.tools.ToolProvider;

/**
 * Lists every @SuppressWarnings and @Generated annotation of the Java files named on the command
 * line as javac's parser reads them: after Unicode escapes, identifier-ignorable characters,
 * comments and line breaks, any of which hides an annotation from a text match while sonar-java
 * still honours it. The Sonar Stop hook refuses each one its line audit could not have read.
 *
 * <p>Prints one tab-separated line per annotation: the path as given, its first line, its kind,
 * its values and its source text with every character outside printable ASCII shown escaped.
 * {@code generated}: named Generated. {@code plain}: a @SuppressWarnings on one line, in printable
 * ASCII, with string literals for values, whose contents follow comma-separated ({@code -} for
 * none, as for the other kinds, so that no field is empty). {@code
 * unreadable}: any other @SuppressWarnings. Names match by their last identifier, so another type
 * of the same simple name counts too.
 *
 * <p>Run: {@code java SuppressionAnnotations.java FILE...}. Exits 1 when a file cannot be read.
 */
public final class SuppressionAnnotations {

  private static final String LITERAL = "\"[^\"\\\\]*\"";
  private static final Pattern PLAIN =
      Pattern.compile(
          "@[ \\t]*(java[ \\t]*\\.[ \\t]*lang[ \\t]*\\.[ \\t]*)?SuppressWarnings[ \\t]*\\([ \\t]*"
              + "(value[ \\t]*=[ \\t]*)?("
              + LITERAL
              + "|\\{[ \\t]*("
              + LITERAL
              + "([ \\t]*,[ \\t]*"
              + LITERAL
              + ")*[ \\t]*,?)?[ \\t]*\\})[ \\t]*\\)");
  private static final Pattern LITERAL_CONTENT = Pattern.compile("\"([^\"]*)\"");
  private static final String NONE = "-";

  private SuppressionAnnotations() {}

  public static void main(String[] args) throws IOException {
    JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
    try (StandardJavaFileManager files =
        compiler.getStandardFileManager(diagnostic -> {}, Locale.ROOT, StandardCharsets.UTF_8)) {
      for (String path : args) {
        JavacTask task =
            (JavacTask)
                compiler.getTask(
                    null,
                    files,
                    diagnostic -> {},
                    List.of("-proc:none"),
                    null,
                    files.getJavaFileObjects(path));
        for (CompilationUnitTree unit : task.parse()) {
          report(path, unit, Trees.instance(task).getSourcePositions());
        }
      }
    }
  }

  private static void report(String path, CompilationUnitTree unit, SourcePositions positions)
      throws IOException {
    String source = unit.getSourceFile().getCharContent(true).toString();
    new TreeScanner<Void, Void>() {
      @Override
      public Void visitAnnotation(AnnotationTree annotation, Void unused) {
        String name = lastIdentifier(annotation.getAnnotationType());
        if (name.equals("SuppressWarnings") || name.equals("Generated")) {
          int start = (int) positions.getStartPosition(unit, annotation);
          int end = (int) positions.getEndPosition(unit, annotation);
          String text = source.substring(start, end);
          String kind = name.equals("Generated") ? "generated" : suppressionKind(text);
          System.out.println(
              String.join(
                  "\t",
                  path,
                  Long.toString(unit.getLineMap().getLineNumber(start)),
                  kind,
                  kind.equals("plain") ? shown(values(text)) : NONE,
                  shown(text)));
        }
        return super.visitAnnotation(annotation, unused);
      }
    }.scan(unit, null);
  }

  private static String lastIdentifier(Tree type) {
    if (type instanceof IdentifierTree identifier) {
      return identifier.getName().toString();
    }
    if (type instanceof MemberSelectTree select) {
      return select.getIdentifier().toString();
    }
    return "";
  }

  private static String suppressionKind(String text) {
    boolean printable = text.chars().allMatch(c -> c == '\t' || (c >= ' ' && c <= '~'));
    return printable && PLAIN.matcher(text).matches() ? "plain" : "unreadable";
  }

  private static String values(String text) {
    StringJoiner joined = new StringJoiner(",");
    Matcher literal = LITERAL_CONTENT.matcher(text);
    while (literal.find()) {
      joined.add(literal.group(1));
    }
    return joined.length() == 0 ? NONE : joined.toString();
  }

  private static String shown(String text) {
    StringBuilder shown = new StringBuilder();
    text.chars()
        .forEach(
            c -> {
              if (c >= ' ' && c <= '~') {
                shown.append((char) c);
              } else {
                shown.append(String.format("\\u%04x", c));
              }
            });
    return shown.toString();
  }
}
